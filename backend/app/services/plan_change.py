"""Cambio de RVOE / de plan: move a student from their current plan to another
plan (same or another carrera) deciding, subject by subject of the new plan below
the destination group's cuatrimestre, what happens with what they studied before:
convalidar / equivalencia / revalidación (recognized, with a grade), cursar ahora
(loaded right away in a group of the term) or pendiente (owed).

A student is never in two RVOE at once: the old plan enrollment is closed (baja) and
the change is recorded in the audit log (action PLAN_CHANGE_ACTION, entity = the new plan
enrollment, detail = JSON with the old one), which is how the kárdex chains both
plans into a single history. No schema change."""
import json
import re
import unicodedata
import uuid
from difflib import SequenceMatcher

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Group,
    GroupEnrollment,
    GroupEnrollmentKind,
    GroupSubject,
    PlanEnrollmentStatus,
    PlanSubject,
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    Term,
)
from app.services import audit
from app.services.academics import (
    PASSING_GRADE,
    PLAN_CHANGE_ACTION,
    get_or_create_plan_enrollment,
    internal_group_clause,
    recognition_kind,
    require_operable_rvoe,
)
from app.services.enrollment import add_subjects_core, enroll_student_core

RECOGNITION_ACTIONS = {"conv": "-CONV", "eq": "-EQ", "rev": "-REV"}
ACTIONS = set(RECOGNITION_ACTIONS) | {"cursar", "pendiente"}


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


async def _current_plan(session: AsyncSession, student: Student, plan_version_id) -> StudentPlanEnrollment:
    plan = (
        await session.exec(
            select(StudentPlanEnrollment).where(
                StudentPlanEnrollment.student_id == student.id,
                StudentPlanEnrollment.plan_version_id == plan_version_id,
                StudentPlanEnrollment.status == PlanEnrollmentStatus.inscrito,
            )
        )
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="El alumno no está inscrito en ese plan")
    return plan


async def _approved_in_plan(session: AsyncSession, student_id, plan_version_id) -> list[dict]:
    """Best approved attempt of each subject of the old plan (what can be recognized)."""
    rows = (
        await session.exec(
            select(SubjectEnrollment, PlanSubject)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .where(
                SubjectEnrollment.student_id == student_id,
                PlanSubject.plan_version_id == plan_version_id,
                SubjectEnrollment.status == SubjectEnrollmentStatus.aprobada,
            )
        )
    ).all()
    best: dict[uuid.UUID, dict] = {}
    for enrollment, subject in rows:
        grade = enrollment.final_grade
        if subject.id not in best or (grade or 0) > (best[subject.id]["grade"] or 0):
            best[subject.id] = {
                "subject_enrollment_id": str(enrollment.id), "plan_subject_id": str(subject.id),
                "code": subject.code, "name": subject.name, "period_number": subject.period_number,
                "grade": grade,
            }
    return sorted(best.values(), key=lambda s: (s["period_number"], s["code"]))


async def _groups_teaching(session: AsyncSession, term_id, campus_id, plan_subject_ids) -> dict:
    rows = (
        await session.exec(
            select(GroupSubject.plan_subject_id, Group)
            .join(Group, Group.id == GroupSubject.group_id)
            .where(
                Group.term_id == term_id,
                Group.campus_id == campus_id,
                GroupSubject.plan_subject_id.in_(plan_subject_ids),  # type: ignore[attr-defined]
                ~internal_group_clause(),
            )
            .order_by(Group.code)
        )
    ).all()
    teaching: dict[uuid.UUID, list[dict]] = {}
    for plan_subject_id, group in rows:
        teaching.setdefault(plan_subject_id, []).append({"group_id": str(group.id), "code": group.code})
    return teaching


async def change_proposal(
    session: AsyncSession, student: Student, from_plan_version_id, target_group: Group
) -> dict:
    """What the change would look like: for every subject of the new plan below the
    destination group's cuatrimestre, a proposed decision. Matches an approved old
    subject by name (accents/punctuation ignored, close spellings accepted),
    preferring the same cuatrimestre; each old subject is used once."""
    old_plan = await _current_plan(session, student, from_plan_version_id)
    if target_group.plan_version_id == old_plan.plan_version_id:
        raise HTTPException(status_code=400, detail="El grupo destino es del mismo plan")
    await require_operable_rvoe(session, target_group.plan_version_id)

    new_subjects = (
        await session.exec(
            select(PlanSubject)
            .where(
                PlanSubject.plan_version_id == target_group.plan_version_id,
                PlanSubject.period_number < target_group.period_number,
            )
            .order_by(PlanSubject.period_number, PlanSubject.code)
        )
    ).all()
    approved = await _approved_in_plan(session, student.id, old_plan.plan_version_id)
    teaching = await _groups_teaching(
        session, target_group.term_id, target_group.campus_id, [s.id for s in new_subjects]
    )

    used: set[str] = set()
    items = []
    for subject in new_subjects:
        name = _norm(subject.name)
        best, best_score = None, 0.0
        for candidate in approved:
            if candidate["subject_enrollment_id"] in used:
                continue
            score = SequenceMatcher(None, name, _norm(candidate["name"])).ratio()
            if candidate["period_number"] == subject.period_number:
                score += 0.05
            if score > best_score:
                best, best_score = candidate, score
        source = best if best and best_score >= 0.8 else None
        if source:
            used.add(source["subject_enrollment_id"])
        items.append({
            "plan_subject_id": str(subject.id), "code": subject.code, "name": subject.name,
            "period_number": subject.period_number, "credits": subject.credits,
            "action": "conv" if source else "cursar",
            "source_subject_enrollment_id": source["subject_enrollment_id"] if source else None,
            "grade": source["grade"] if source else None,
            "groups": teaching.get(subject.id, []),
        })
    return {
        "from_plan_version_id": str(old_plan.plan_version_id),
        "target_group_id": str(target_group.id),
        "target_plan_version_id": str(target_group.plan_version_id),
        "target_period_number": target_group.period_number,
        "items": items,
        "approved": approved,  # options for picking another source subject
    }


async def _recognition_group(session: AsyncSession, target_group: Group, suffix: str) -> Group:
    code = f"{target_group.code}{suffix}"[:32]
    group = (
        await session.exec(
            select(Group).where(
                Group.term_id == target_group.term_id,
                Group.campus_id == target_group.campus_id,
                Group.code == code,
            )
        )
    ).first()
    if group is None:
        group = Group(
            code=code, period_number=1, is_active=False,  # internal: nobody attends it
            plan_version_id=target_group.plan_version_id, term_id=target_group.term_id,
            campus_id=target_group.campus_id,
        )
        session.add(group)
        await session.flush()
    assert recognition_kind(group.code)
    return group


async def apply_change(
    session: AsyncSession, current_user, student: Student, from_plan_version_id,
    target_group: Group, decisions: list[dict],
) -> dict:
    """Close the old plan, enroll into the destination group and apply each
    decision. Caller commits."""
    old_plan = await _current_plan(session, student, from_plan_version_id)
    if target_group.plan_version_id == old_plan.plan_version_id:
        raise HTTPException(status_code=400, detail="El grupo destino es del mismo plan")
    await require_operable_rvoe(session, target_group.plan_version_id)
    term = await session.get(Term, target_group.term_id)

    subjects = {
        s.id: s for s in (
            await session.exec(
                select(PlanSubject).where(PlanSubject.plan_version_id == target_group.plan_version_id)
            )
        ).all()
    }
    for d in decisions:
        if d["action"] not in ACTIONS:
            raise HTTPException(status_code=400, detail=f"Decisión inválida: {d['action']}")
        subject = subjects.get(uuid.UUID(str(d["plan_subject_id"])))
        if subject is None or subject.period_number >= target_group.period_number:
            raise HTTPException(status_code=400, detail="Materia fuera de la propuesta del plan nuevo")
        if d["action"] == "conv" and d.get("grade") is None:
            raise HTTPException(status_code=400, detail=f"{subject.name}: falta la calificación")
        grade = d.get("grade")
        if grade is not None and not 0 <= float(grade) <= 10:
            raise HTTPException(status_code=400, detail=f"{subject.name}: calificación fuera de 0–10")

    # never in two RVOE at once
    old_plan.status = PlanEnrollmentStatus.baja
    session.add(old_plan)
    if student.campus_id != target_group.campus_id:  # e.g. presencial -> online
        student.campus_id = target_group.campus_id
        session.add(student)
    new_plan, _ = await get_or_create_plan_enrollment(
        session, student, target_group.plan_version_id, target_group.term_id
    )
    if new_plan.status != PlanEnrollmentStatus.inscrito:
        new_plan.status = PlanEnrollmentStatus.inscrito
        session.add(new_plan)

    summary = {k: [] for k in ACTIONS}
    # recognitions first, then other groups, then the destination group last: the
    # student header shows the most recent active group
    for kind, suffix in RECOGNITION_ACTIONS.items():
        chosen = [d for d in decisions if d["action"] == kind]
        if not chosen:
            continue
        group = await _recognition_group(session, target_group, suffix)
        enrollment = GroupEnrollment(
            student_id=student.id, group_id=group.id, plan_enrollment_id=new_plan.id,
            kind=GroupEnrollmentKind.reinscripcion,
        )
        session.add(enrollment)
        await session.flush()
        for d in chosen:
            subject = subjects[uuid.UUID(str(d["plan_subject_id"]))]
            gs = (
                await session.exec(
                    select(GroupSubject).where(
                        GroupSubject.group_id == group.id, GroupSubject.plan_subject_id == subject.id
                    )
                )
            ).first()
            if gs is None:
                gs = GroupSubject(group_id=group.id, plan_subject_id=subject.id)
                session.add(gs)
                await session.flush()
            grade = d.get("grade")
            session.add(SubjectEnrollment(
                group_enrollment_id=enrollment.id, group_subject_id=gs.id, student_id=student.id,
                status=(
                    SubjectEnrollmentStatus.cursando if grade is None  # EQ/REV pendiente
                    else SubjectEnrollmentStatus.aprobada if float(grade) >= PASSING_GRADE
                    else SubjectEnrollmentStatus.reprobada
                ),
                final_grade=float(grade) if grade is not None else None,
            ))
            summary[kind].append(subject.code)

    elsewhere: dict[str, list] = {}
    in_target = []
    for d in decisions:
        if d["action"] != "cursar":
            continue
        group_id = str(d.get("group_id") or target_group.id)
        (in_target if group_id == str(target_group.id) else elsewhere.setdefault(group_id, [])).append(
            uuid.UUID(str(d["plan_subject_id"]))
        )
    for group_id, subject_ids in elsewhere.items():
        group = await session.get(Group, uuid.UUID(group_id))
        if group is None or group.term_id != target_group.term_id or group.plan_version_id != target_group.plan_version_id:
            raise HTTPException(status_code=400, detail="Grupo inválido para cursar la materia")
        await enroll_student_core(
            session, current_user, student, group,
            plan_subject_ids=subject_ids, override_prerequisites=True,
        )
        summary["cursar"] += [subjects[i].code for i in subject_ids]

    await enroll_student_core(session, current_user, student, target_group)
    if in_target:
        await add_subjects_core(
            session, current_user, student, target_group,
            plan_subject_ids=in_target, override_prerequisites=True,
        )
        summary["cursar"] += [subjects[i].code for i in in_target]
    summary["pendiente"] = [
        subjects[uuid.UUID(str(d["plan_subject_id"]))].code for d in decisions if d["action"] == "pendiente"
    ]

    audit.record(
        session, actor=current_user.email, action=PLAN_CHANGE_ACTION,
        entity="plan_enrollment", entity_id=str(new_plan.id),
        detail=json.dumps({
            "from_plan_enrollment_id": str(old_plan.id),
            "from_plan_version_id": str(old_plan.plan_version_id),
            "to_plan_version_id": str(target_group.plan_version_id),
            "target_group": target_group.code, "term": term.name if term else None,
            "decisions": decisions,
        }, ensure_ascii=False, default=str),
    )
    await session.flush()
    return {"new_plan_enrollment_id": str(new_plan.id), "summary": summary}
