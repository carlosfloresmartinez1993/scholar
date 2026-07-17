"""Cycle promotion (reinscripción): for each next-term group linked via
promotes_from_group_id, move the source group's continuing, PASSING students up —
enrolling + auto-billing reinscripción and the new term's colegiaturas. Idempotent
(re-runs skip already-promoted students), supports a dry-run preview, and isolates
each student in a SAVEPOINT so one failure never rolls back the batch. Driven by a
Railway cron that fires PROMOTION_LEAD_DAYS before a term's start_date."""
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
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    Term,
)
from app.models.common import utcnow
from app.services import audit
from app.services.enrollment import enroll_student_core


async def _passed_source_group(
    session: AsyncSession, group_enrollment_id, source_group_id
) -> bool:
    """True only if the student passed EVERY subject of the source group. A partial
    enrollment (they took only some subjects) or any non-aprobada means they repeat,
    so they don't advance."""
    required = set(
        (
            await session.exec(
                select(GroupSubject.plan_subject_id).where(
                    GroupSubject.group_id == source_group_id
                )
            )
        ).all()
    )
    if not required:
        return False
    passed = set(
        (
            await session.exec(
                select(GroupSubject.plan_subject_id)
                .join(SubjectEnrollment, SubjectEnrollment.group_subject_id == GroupSubject.id)
                .where(
                    SubjectEnrollment.group_enrollment_id == group_enrollment_id,
                    SubjectEnrollment.status == SubjectEnrollmentStatus.aprobada,
                )
            )
        ).all()
    )
    return required <= passed


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
    for target, term in targets:
        enrollments = (
            await session.exec(
                select(GroupEnrollment, Student)
                .join(Student, Student.id == GroupEnrollment.student_id)
                .where(
                    GroupEnrollment.group_id == target.promotes_from_group_id,
                    GroupEnrollment.status == GroupEnrollmentStatus.activa,
                )
            )
        ).all()
        for en, student in enrollments:
            info = {
                "student": student.full_name,
                "matricula": student.enrollment_number,
                "target_group": target.code,
                "term": term.name,
            }
            # idempotent: already in the target group?
            already = (
                await session.exec(
                    select(GroupEnrollment.id).where(
                        GroupEnrollment.student_id == student.id,
                        GroupEnrollment.group_id == target.id,
                    )
                )
            ).first()
            if already:
                continue
            # continuing? plan enrollment must be inscrito (not baja/egresado/titulado)
            plan_en = await session.get(StudentPlanEnrollment, en.plan_enrollment_id)
            if plan_en is None or plan_en.status != PlanEnrollmentStatus.inscrito:
                skipped.append({**info, "reason": "no continúa (baja/egresado)"})
                continue
            # passed the whole source period?
            if not await _passed_source_group(session, en.id, target.promotes_from_group_id):
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
