"""Cycle promotion (reinscripción): for each next-term group linked via
promotes_from_group_id, move the source group's continuing, PASSING students up —
enrolling + auto-billing reinscripción and the new term's colegiaturas. Idempotent
(re-runs skip already-promoted students), supports a dry-run preview, and isolates
each student in a SAVEPOINT so one failure never rolls back the batch. Driven by a
Railway cron that fires PROMOTION_LEAD_DAYS before a term's start_date."""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import (
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    GroupSubject,
    PlanEnrollmentStatus,
    PlanSubject,
    Student,
    StudentStatus,
    StudentPlanEnrollment,
    Term,
)
from app.models.common import utcnow
from app.services import audit
from app.services.academics import current_groups_of, settled_subjects_of
from app.services.enrollment import enroll_student_core


async def promote_cycle(
    session: AsyncSession,
    current_user,
    *,
    institution_id=None,
    today: date | None = None,
    lead_days: int | None = None,
    dry_run: bool = True,
) -> dict:
    """Promote every eligible student into their linked next-term group. Returns a
    summary of promoted + skipped (with reasons). dry_run changes nothing. Pass
    institution_id to scope to one tenant (the interactive path always does); the
    cron leaves it None for an intentional global run."""
    today = today or utcnow().date()
    lead_days = settings.PROMOTION_LEAD_DAYS if lead_days is None else lead_days
    cutoff = today + timedelta(days=lead_days)

    # target groups: explicitly linked, in a term that starts within the lead
    # window and hasn't ended (so late-captured grades still get picked up).
    query = (
        select(Group, Term)
        .join(Term, Term.id == Group.term_id)
        .where(
            Group.promotes_from_group_id.is_not(None),  # type: ignore[union-attr]
            Term.start_date <= cutoff,
            Term.end_date >= today,
        )
    )
    if institution_id is not None:
        query = query.where(Term.institution_id == institution_id)
    targets = (await session.exec(query)).all()

    promoted: list[dict] = []
    skipped: list[dict] = []
    # everything the decision needs is read once for all the students; a promotion
    # with thousands of them is not thousands of round trips for each question
    source_ids = {target.promotes_from_group_id for target, _ in targets}
    target_ids = {target.id for target, _ in targets}
    in_sources = select(GroupEnrollment.student_id).where(
        GroupEnrollment.group_id.in_(source_ids),  # type: ignore[attr-defined]
        GroupEnrollment.status == GroupEnrollmentStatus.activa,
        GroupEnrollment.subjects_only == False,  # noqa: E712
    )
    by_source: dict = defaultdict(list)
    for en, student, plan_status in (
        await session.exec(
            select(GroupEnrollment, Student, StudentPlanEnrollment.status)
            .join(Student, Student.id == GroupEnrollment.student_id)
            .join(StudentPlanEnrollment, StudentPlanEnrollment.id == GroupEnrollment.plan_enrollment_id)
            .where(
                GroupEnrollment.group_id.in_(source_ids),  # type: ignore[attr-defined]
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
                # a subject taken there from another group does not move the student
                GroupEnrollment.subjects_only == False,  # noqa: E712
            )
        )
    ).all():
        by_source[en.group_id].append((en, student, plan_status))
    already = set(
        (
            await session.exec(
                select(GroupEnrollment.student_id, GroupEnrollment.group_id).where(
                    GroupEnrollment.group_id.in_(target_ids)  # type: ignore[attr-defined]
                )
            )
        ).all()
    )
    source_groups = {
        g.id: g for g in (await session.exec(select(Group).where(Group.id.in_(source_ids)))).all()  # type: ignore[attr-defined]
    }
    # what each group asks: the subjects it teaches of its own cuatrimestre (one added
    # for a student's recursamiento is not asked of the others); passed in any group,
    # or recognized by EQ/REV/CONV even without a grade yet
    taught: dict = defaultdict(list)
    for group_id, subject_id, period in (
        await session.exec(
            select(GroupSubject.group_id, GroupSubject.plan_subject_id, PlanSubject.period_number)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .where(GroupSubject.group_id.in_(source_ids))  # type: ignore[attr-defined]
        )
    ).all():
        taught[group_id].append((subject_id, period))
    required = {}
    for group_id, subjects in taught.items():
        own = {subject for subject, period in subjects if period == source_groups[group_id].period_number}
        required[group_id] = own or {subject for subject, _ in subjects}
    settled = await settled_subjects_of(session, in_sources)
    main_groups = await current_groups_of(session, in_sources)

    for target, term in targets:
        source_group = source_groups[target.promotes_from_group_id]
        for en, student, plan_status in by_source[source_group.id]:
            info = {
                "student": student.full_name,
                "matricula": student.enrollment_number,
                "target_group": target.code,
                "term": term.name,
            }
            # idempotent: already in the target group?
            if (student.id, target.id) in already:
                continue
            # de baja (temporal or definitiva): stays where they were, history intact
            if student.status in (StudentStatus.baja_temporal, StudentStatus.baja_definitiva):
                kind = "temporal" if student.status == StudentStatus.baja_temporal else "definitiva"
                skipped.append({**info, "reason": f"de baja {kind}"})
                continue
            # continuing? plan enrollment must be inscrito (not baja/egresado/titulado)
            if plan_status != PlanEnrollmentStatus.inscrito:
                skipped.append({**info, "reason": "no continúa (baja/egresado)"})
                continue
            # only from the group they really are in: a lower one is a recursamiento
            main_group = main_groups.get((student.id, source_group.plan_version_id))
            if main_group is not None and main_group.period_number > source_group.period_number:
                skipped.append({**info, "reason": f"recursa en este grupo; su grupo es {main_group.code}"})
                continue
            # passed the whole source period?
            wanted = required.get(source_group.id)
            if not wanted or not wanted <= settled.get(student.id, set()):
                skipped.append({**info, "reason": "no acreditó el periodo"})
                continue
            if dry_run:
                promoted.append(info)
                continue
            try:  # isolate each student so one failure doesn't sink the batch
                async with session.begin_nested():
                    await enroll_student_core(session, current_user, student, target)
                promoted.append(info)
            except (HTTPException, IntegrityError, ValueError) as e:
                detail = e.detail if isinstance(e, HTTPException) else str(e)
                skipped.append({**info, "reason": f"error: {detail}"})

    if not dry_run and (promoted or skipped):
        audit.record(
            session, actor=current_user.email, action="cycle.promoted",
            entity="institution", entity_id=str(getattr(current_user, "institution_id", "-")),
            detail=f"{len(promoted)} promovidos, {len(skipped)} omitidos",
        )
        await session.commit()
    return {
        "dry_run": dry_run,
        "promoted_count": len(promoted),
        "skipped_count": len(skipped),
        "promoted": promoted,
        "skipped": skipped,
    }
