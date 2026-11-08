"""Cambio de RVOE / de plan: move a student from their current plan to another
plan (same or another carrera) deciding, subject by subject of the new plan below
the destination group's cuatrimestre, what happens with what they studied before:
convalidar / equivalencia / revalidación (recognized, with a grade), cursar ahora
(loaded right away in a group of the term) or pendiente (owed).

A student is never in two RVOE at once: the old plan enrollment is closed (baja) and
the change is recorded in plan_changes, which is how the kárdex chains both plans into
a single history (and how it is reverted)."""
import json
import re
import unicodedata
import uuid
from datetime import datetime
from difflib import SequenceMatcher

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Charge,
    ChargeStatus,
    Grade,
    Group,
    GroupEnrollment,
    GroupEnrollmentKind,
    GroupEnrollmentStatus,
    GroupSubject,
    PlanChange,
    PlanEnrollmentStatus,
    PlanSubject,
    PlanVersion,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    SubjectRecognition,
    Term,
)
from app.models.common import utcnow
from app.services import audit
from app.services.academics import (
    PASSING_GRADE,
    PLAN_CHANGE_ACTION,
    PLAN_CHANGE_REVERTED_ACTION,
    RECOGNITION_ACTION,
    active_plan_changes,
    current_group,
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


async def _plan_history(session: AsyncSession, student_id, plan_version_id) -> list[dict]:
    """Every subject of the old plan with the student's best result in it, for the
    side-by-side view of the cambio de RVOE (aprobada > cursando > reprobada > sin cursar)."""
    rank = {SubjectEnrollmentStatus.aprobada: 3, SubjectEnrollmentStatus.cursando: 2,
            SubjectEnrollmentStatus.reprobada: 1, SubjectEnrollmentStatus.baja: 0}
    best: dict[uuid.UUID, SubjectEnrollment] = {}
    for enrollment, plan_subject_id in (
        await session.exec(
            select(SubjectEnrollment, GroupSubject.plan_subject_id)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .where(SubjectEnrollment.student_id == student_id,
                   SubjectEnrollment.status != SubjectEnrollmentStatus.baja)
        )
    ).all():
        current = best.get(plan_subject_id)
        if current is None or rank[enrollment.status] > rank[current.status]:
            best[plan_subject_id] = enrollment
    subjects = (
        await session.exec(
            select(PlanSubject)
            .where(PlanSubject.plan_version_id == plan_version_id)
            .order_by(PlanSubject.period_number, PlanSubject.code)
        )
    ).all()
    return [
        {"code": s.code, "name": s.name, "period_number": s.period_number,
         "status": best[s.id].status if s.id in best else "sin_cursar",
         "grade": best[s.id].final_grade if s.id in best else None}
        for s in subjects
    ]


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
            .where(PlanSubject.plan_version_id == target_group.plan_version_id)
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
            # no adelantar: only what is below the destination can be taken now
            "action": "conv" if source else (
                "cursar" if subject.period_number < target_group.period_number else "pendiente"),
            "source_subject_enrollment_id": source["subject_enrollment_id"] if source else None,
            "grade": source["grade"] if source else None,
            "groups": teaching.get(subject.id, []),
        })
    return {
        "from_plan_version_id": str(old_plan.plan_version_id),
        "from_rvoe": await _plan_rvoe(session, old_plan.plan_version_id),
        "old_subjects": await _plan_history(session, student.id, old_plan.plan_version_id),
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


async def _plan_rvoe(session: AsyncSession, plan_version_id) -> str:
    plan = await session.get(PlanVersion, plan_version_id)
    rvoe = plan and await session.get(Rvoe, plan.rvoe_id)
    return rvoe.agreement_number if rvoe else ""


def _classify(rows: list[tuple[SubjectEnrollment, Group]], captured: set) -> tuple[str, list[SubjectEnrollment]]:
    """Where a subject of the plan stands for a recognition: libre (nothing recorded),
    en_curso (loaded in a group, no evaluations: returned so it can be replaced),
    evaluada (has a final grade or captures) or reconocida (already EQ/REV/CONV)."""
    if any(recognition_kind(group.code) for _, group in rows):
        return "reconocida", []
    enrollments = [se for se, _ in rows]
    if any(
        se.id in captured or se.final_grade is not None or se.status != SubjectEnrollmentStatus.cursando
        for se in enrollments
    ):
        return "evaluada", []
    return ("en_curso", enrollments) if enrollments else ("libre", [])


async def _subject_rows(session: AsyncSession, student_id, *conditions) -> tuple[dict, set]:
    """Non-dropped rows of the student per plan subject, and which have captures."""
    rows: dict = {}
    for se, group, subject_id in (
        await session.exec(
            select(SubjectEnrollment, Group, GroupSubject.plan_subject_id)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(Group, Group.id == GroupSubject.group_id)
            .where(
                SubjectEnrollment.student_id == student_id,
                SubjectEnrollment.status != SubjectEnrollmentStatus.baja,
                *conditions,
            )
        )
    ).all():
        rows.setdefault(subject_id, []).append((se, group))
    ids = [se.id for found in rows.values() for se, _ in found]
    captured = set(
        (
            await session.exec(
                select(Grade.subject_enrollment_id).where(
                    Grade.subject_enrollment_id.in_(ids or [uuid.uuid4()])  # type: ignore[attr-defined]
                )
            )
        ).all()
    )
    return rows, captured


async def _subject_state(
    session: AsyncSession, student_id, plan_subject_id
) -> tuple[str, list[SubjectEnrollment]]:
    rows, captured = await _subject_rows(session, student_id, GroupSubject.plan_subject_id == plan_subject_id)
    return _classify(rows.get(plan_subject_id, []), captured)


async def record_recognitions(
    session: AsyncSession, current_user, student: Student, anchor_group: Group,
    plan_enrollment: StudentPlanEnrollment, items: list[dict],
) -> list[SubjectEnrollment]:
    """Record subjects recognized by equivalencia / revalidación / convalidación in
    the internal group of `anchor_group` ("<code>-EQ", ...). Each item: subject
    (PlanSubject), kind (eq|rev|conv), grade (None = pending the authority's
    document) and origin (where it comes from: RVOE and subject, or the external
    school / document), kept in subject_recognitions and shown in the kárdex.
    Caller commits."""
    created = []
    enrollments: dict[str, GroupEnrollment] = {}
    for item in items:
        subject, kind = item["subject"], item["kind"]
        state, in_course = await _subject_state(session, student.id, subject.id)
        if state == "evaluada":
            raise HTTPException(
                status_code=409,
                detail=f"{subject.name}: no se puede marcar porque tiene evaluaciones registradas. "
                "Primero corrija su calificación.",
            )
        if state == "reconocida":
            raise HTTPException(
                status_code=409, detail=f"{subject.name}: ya está reconocida; use «Corregir» en el kárdex"
            )
        # loaded by the group but without evaluations: the recognition replaces it.
        # The student stays in the group (never without one).
        for row in in_course:
            row.status = SubjectEnrollmentStatus.baja
            session.add(row)
            audit.record(
                session, actor=current_user.email, action="subject_enrollment.dropped",
                entity="subject_enrollment", entity_id=str(row.id),
                detail=f"{subject.code}: reconocida como {kind.upper()}",
            )
        if kind not in enrollments:
            group = await _recognition_group(session, anchor_group, RECOGNITION_ACTIONS[kind])
            enrollment = (
                await session.exec(
                    select(GroupEnrollment).where(
                        GroupEnrollment.student_id == student.id, GroupEnrollment.group_id == group.id
                    )
                )
            ).first()
            if enrollment is None:
                enrollment = GroupEnrollment(
                    student_id=student.id, group_id=group.id, plan_enrollment_id=plan_enrollment.id,
                    kind=GroupEnrollmentKind.reinscripcion,
                )
                session.add(enrollment)
                await session.flush()
            enrollments[kind] = enrollment
        enrollment = enrollments[kind]
        gs = (
            await session.exec(
                select(GroupSubject).where(
                    GroupSubject.group_id == enrollment.group_id, GroupSubject.plan_subject_id == subject.id
                )
            )
        ).first()
        if gs is None:
            gs = GroupSubject(group_id=enrollment.group_id, plan_subject_id=subject.id)
            session.add(gs)
            await session.flush()
        grade = item.get("grade")
        recognized = SubjectEnrollment(
            group_enrollment_id=enrollment.id, group_subject_id=gs.id, student_id=student.id,
            status=_status_for(grade), final_grade=float(grade) if grade is not None else None,
        )
        session.add(recognized)
        await session.flush()
        session.add(SubjectRecognition(subject_enrollment_id=recognized.id, origin=item.get("origin") or ""))
        audit.record(
            session, actor=current_user.email, action=RECOGNITION_ACTION,
            entity="subject_enrollment", entity_id=str(recognized.id),
            detail=json.dumps({"kind": kind, "origin": item.get("origin") or "", "grade": grade,
                               "subject": subject.code}, ensure_ascii=False),
        )
        created.append(recognized)
    return created


def _status_for(grade) -> SubjectEnrollmentStatus:
    if grade is None:
        return SubjectEnrollmentStatus.cursando  # EQ/REV/CONV pendiente del documento
    return SubjectEnrollmentStatus.aprobada if float(grade) >= PASSING_GRADE else SubjectEnrollmentStatus.reprobada


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
        if subject is None:
            raise HTTPException(status_code=400, detail="Materia fuera del plan nuevo")
        if d["action"] == "cursar" and subject.period_number >= target_group.period_number:
            raise HTTPException(
                status_code=400, detail=f"{subject.name}: no es anterior al cuatrimestre del grupo destino"
            )
        if d["action"] == "conv" and d.get("grade") is None:
            raise HTTPException(status_code=400, detail=f"{subject.name}: falta la calificación")
        grade = d.get("grade")
        if grade is not None and not 0 <= float(grade) <= 10:
            raise HTTPException(status_code=400, detail=f"{subject.name}: calificación fuera de 0–10")

    started_at = utcnow()
    from_campus_id = student.campus_id
    # never in two RVOE at once: the old plan closes, and with it its groups and the
    # subjects in course (recognitions pending a document stay on record). What is
    # closed here is listed in the audit entry, so the change can be reverted.
    old_plan.status = PlanEnrollmentStatus.baja
    session.add(old_plan)
    closed_groups = (
        await session.exec(
            select(GroupEnrollment)
            .join(Group, Group.id == GroupEnrollment.group_id)
            .where(
                GroupEnrollment.plan_enrollment_id == old_plan.id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
                ~internal_group_clause(),
            )
        )
    ).all()
    dropped_subjects = (
        await session.exec(
            select(SubjectEnrollment).where(
                SubjectEnrollment.group_enrollment_id.in_([g.id for g in closed_groups] or [uuid.uuid4()]),  # type: ignore[attr-defined]
                SubjectEnrollment.status == SubjectEnrollmentStatus.cursando,
            )
        )
    ).all()
    closed_group_ids = [str(g.id) for g in closed_groups]
    dropped_subject_ids = [str(s.id) for s in dropped_subjects]
    for closed in closed_groups:
        closed.status = GroupEnrollmentStatus.baja
        session.add(closed)
    for dropped in dropped_subjects:
        dropped.status = SubjectEnrollmentStatus.baja
        session.add(dropped)
    if student.campus_id != target_group.campus_id:  # e.g. presencial -> online
        student.campus_id = target_group.campus_id
        session.add(student)
    new_plan, new_plan_created = await get_or_create_plan_enrollment(
        session, student, target_group.plan_version_id, target_group.term_id
    )
    if new_plan.status != PlanEnrollmentStatus.inscrito:
        new_plan.status = PlanEnrollmentStatus.inscrito
        session.add(new_plan)

    summary = {k: [] for k in ACTIONS}
    # recognitions first, then other groups, then the destination group last: the
    # student header shows the most recent active group
    sources = {a["subject_enrollment_id"]: a for a in await _approved_in_plan(
        session, student.id, old_plan.plan_version_id)}
    old_rvoe = await _plan_rvoe(session, old_plan.plan_version_id)
    recognized = []
    for d in decisions:
        if d["action"] not in RECOGNITION_ACTIONS:
            continue
        source = sources.get(str(d.get("source_subject_enrollment_id") or ""))
        recognized.append({
            "subject": subjects[uuid.UUID(str(d["plan_subject_id"]))], "kind": d["action"],
            "grade": d.get("grade"),
            "origin": f"{old_rvoe} · {source['code']} {source['name']}" if source else old_rvoe,
        })
    await record_recognitions(session, current_user, student, target_group, new_plan, recognized)
    for item in recognized:
        summary[item["kind"]].append(item["subject"].code)

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

    session.add(PlanChange(
        student_id=student.id, from_plan_enrollment_id=old_plan.id, to_plan_enrollment_id=new_plan.id,
        changed_by=current_user.email,
        detail=json.loads(json.dumps({
            "from_plan_version_id": old_plan.plan_version_id,
            "to_plan_version_id": target_group.plan_version_id,
            "target_group": target_group.code, "term": term.name if term else None,
            "decisions": decisions,
            # to revert it
            "started_at": started_at.isoformat(), "from_campus_id": from_campus_id,
            "new_plan_created": new_plan_created,
            "closed_group_enrollment_ids": closed_group_ids,
            "dropped_subject_enrollment_ids": dropped_subject_ids,
        }, default=str)),
    ))
    audit.record(
        session, actor=current_user.email, action=PLAN_CHANGE_ACTION,
        entity="plan_enrollment", entity_id=str(new_plan.id),
        detail=f"{old_plan.plan_version_id} -> {target_group.plan_version_id}, grupo {target_group.code}",
    )
    await session.flush()
    return {"new_plan_enrollment_id": str(new_plan.id), "summary": summary}


# --- Reconocimiento de estudios previos (alumno que entra con certificado parcial) --

async def _current_group(session: AsyncSession, student: Student, plan_version_id) -> Group:
    """The group the student really is in, in that plan (the highest active)."""
    group = await current_group(session, student.id, plan_version_id)
    if group is None:
        raise HTTPException(status_code=404, detail="El alumno no tiene grupo en ese plan")
    return group


async def recognition_candidates(session: AsyncSession, student: Student, plan_version_id) -> dict:
    """The whole plan of the RVOE with where each subject stands: a certificate can
    cover any of them, even ahead of the student's cuatrimestre (EQ/REV/CONV)."""
    await _current_plan(session, student, plan_version_id)
    group = await _current_group(session, student, plan_version_id)
    subjects = (
        await session.exec(
            select(PlanSubject)
            .where(PlanSubject.plan_version_id == plan_version_id)
            .order_by(PlanSubject.period_number, PlanSubject.code)
        )
    ).all()
    rows, captured = await _subject_rows(
        session, student.id, GroupSubject.plan_subject_id.in_([s.id for s in subjects] or [uuid.uuid4()])  # type: ignore[attr-defined]
    )
    states = {s.id: _classify(rows.get(s.id, []), captured)[0] for s in subjects}
    return {
        "group_id": str(group.id), "group_code": group.code, "period_number": group.period_number,
        "subjects": [
            {"plan_subject_id": str(s.id), "code": s.code, "name": s.name,
             "period_number": s.period_number, "credits": s.credits, "state": states[s.id]}
            for s in subjects
        ],
    }


async def recognize_prior_studies(
    session: AsyncSession, current_user, student: Student, plan_version_id, items: list[dict]
) -> list[SubjectEnrollment]:
    """Mark subjects of the plan as EQ/REV/CONV, in any cuatrimestre — pending (no
    grade) until the authority's document arrives, or with its grade. Caller commits."""
    plan_enrollment = await _current_plan(session, student, plan_version_id)
    group = await _current_group(session, student, plan_version_id)
    if not items:
        raise HTTPException(status_code=400, detail="Seleccione al menos una materia")
    subjects = {
        s.id: s for s in (
            await session.exec(select(PlanSubject).where(PlanSubject.plan_version_id == plan_version_id))
        ).all()
    }
    prepared = []
    for item in items:
        subject = subjects.get(uuid.UUID(str(item["plan_subject_id"])))
        if subject is None:
            raise HTTPException(status_code=400, detail="La materia no es del plan del alumno")
        if item["kind"] not in RECOGNITION_ACTIONS:
            raise HTTPException(status_code=400, detail=f"Tipo inválido: {item['kind']}")
        grade = item.get("grade")
        if grade is not None and not 0 <= float(grade) <= 10:
            raise HTTPException(status_code=400, detail=f"{subject.name}: calificación fuera de 0–10")
        prepared.append({"subject": subject, "kind": item["kind"], "grade": grade,
                         "origin": (item.get("origin") or "").strip()})
    return await record_recognitions(session, current_user, student, group, plan_enrollment, prepared)


async def set_official_grade(
    session: AsyncSession, current_user, enrollment: SubjectEnrollment, grade: float
) -> SubjectEnrollment:
    """Record the authority's grade on a recognized (EQ/REV/CONV) subject."""
    group = (
        await session.exec(
            select(Group)
            .join(GroupSubject, GroupSubject.group_id == Group.id)
            .where(GroupSubject.id == enrollment.group_subject_id)
        )
    ).first()
    if group is None or recognition_kind(group.code) is None:
        raise HTTPException(
            status_code=400, detail="Solo materias por equivalencia, revalidación o convalidación"
        )
    if not 0 <= grade <= 10:
        raise HTTPException(status_code=400, detail="La calificación debe estar entre 0 y 10")
    before = enrollment.final_grade
    enrollment.final_grade = float(grade)
    enrollment.status = _status_for(grade)
    session.add(enrollment)
    audit.record(
        session, actor=current_user.email, action="subject_enrollment.official_grade",
        entity="subject_enrollment", entity_id=str(enrollment.id),
        detail=f"{recognition_kind(group.code).upper()}: {before if before is not None else 'pendiente'} -> {grade}",
    )
    return enrollment


# --- Correcciones: el error humano existe ---------------------------------------------

async def update_recognition(
    session: AsyncSession, current_user, enrollment: SubjectEnrollment, *,
    kind: str, grade: float | None, origin: str, reason: str,
) -> SubjectEnrollment:
    """Fix a recognized subject: its kind (it moves to that internal group), its
    grade (None = pending the document) and its origin. Caller commits."""
    if kind not in RECOGNITION_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Tipo inválido: {kind}")
    gs = await session.get(GroupSubject, enrollment.group_subject_id)
    group = await session.get(Group, gs.group_id) if gs else None
    current_kind = recognition_kind(group.code) if group else None
    if current_kind is None:
        raise HTTPException(
            status_code=400, detail="Solo materias por equivalencia, revalidación o convalidación"
        )
    subject = await session.get(PlanSubject, gs.plan_subject_id)
    before = enrollment.final_grade
    if kind != current_kind:
        base = group.code[: -len(RECOGNITION_ACTIONS[current_kind])]
        anchor = Group(code=base, term_id=group.term_id, campus_id=group.campus_id,
                       plan_version_id=group.plan_version_id)
        target = await _recognition_group(session, anchor, RECOGNITION_ACTIONS[kind])
        current = await session.get(GroupEnrollment, enrollment.group_enrollment_id)
        moved = (
            await session.exec(
                select(GroupEnrollment).where(
                    GroupEnrollment.student_id == enrollment.student_id,
                    GroupEnrollment.group_id == target.id,
                )
            )
        ).first()
        if moved is None:
            moved = GroupEnrollment(
                student_id=enrollment.student_id, group_id=target.id,
                plan_enrollment_id=current.plan_enrollment_id, kind=GroupEnrollmentKind.reinscripcion,
            )
            session.add(moved)
            await session.flush()
        target_gs = (
            await session.exec(
                select(GroupSubject).where(
                    GroupSubject.group_id == target.id, GroupSubject.plan_subject_id == gs.plan_subject_id
                )
            )
        ).first()
        if target_gs is None:
            target_gs = GroupSubject(group_id=target.id, plan_subject_id=gs.plan_subject_id)
            session.add(target_gs)
            await session.flush()
        clash = (
            await session.exec(
                select(SubjectEnrollment.id).where(
                    SubjectEnrollment.group_enrollment_id == moved.id,
                    SubjectEnrollment.group_subject_id == target_gs.id,
                )
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail=f"{subject.name} ya está registrada como {kind.upper()}")
        enrollment.group_enrollment_id = moved.id
        enrollment.group_subject_id = target_gs.id
    enrollment.final_grade = float(grade) if grade is not None else None
    enrollment.status = _status_for(grade)
    session.add(enrollment)
    recognition = await session.get(SubjectRecognition, enrollment.id)
    if recognition is None:
        recognition = SubjectRecognition(subject_enrollment_id=enrollment.id)
    recognition.origin = origin.strip()
    recognition.updated_at = utcnow()
    session.add(recognition)
    # the audit log keeps the earlier values as history
    audit.record(
        session, actor=current_user.email, action=RECOGNITION_ACTION,
        entity="subject_enrollment", entity_id=str(enrollment.id),
        detail=json.dumps({
            "kind": kind, "origin": origin.strip(), "grade": grade, "subject": subject.code,
            "corrected_from": {"kind": current_kind, "grade": before}, "reason": reason.strip(),
        }, ensure_ascii=False),
    )
    await session.flush()
    return enrollment


async def _delete_enrollment(session: AsyncSession, enrollment: SubjectEnrollment) -> None:
    recognition = await session.get(SubjectRecognition, enrollment.id)
    if recognition is not None:
        await session.delete(recognition)
        await session.flush()
    await session.delete(enrollment)


async def undo_recognition(
    session: AsyncSession, current_user, enrollment: SubjectEnrollment, reason: str
) -> None:
    """The subject should not have been recognized. It stays in its period of the
    plan (the RVOE is untouchable), pending; only the recognition goes, kept in the
    audit log. Caller commits."""
    gs = await session.get(GroupSubject, enrollment.group_subject_id)
    group = await session.get(Group, gs.group_id) if gs else None
    kind = recognition_kind(group.code) if group else None
    if kind is None:
        raise HTTPException(
            status_code=400, detail="Solo materias por equivalencia, revalidación o convalidación"
        )
    subject = await session.get(PlanSubject, gs.plan_subject_id)
    audit.record(
        session, actor=current_user.email, action="subject_enrollment.recognition_undone",
        entity="subject_enrollment", entity_id=str(enrollment.id),
        detail=json.dumps({"kind": kind, "grade": enrollment.final_grade, "subject": subject.code,
                           "group": group.code, "reason": reason.strip()}, ensure_ascii=False),
    )
    await _delete_enrollment(session, enrollment)
    await session.flush()


async def revert_change(
    session: AsyncSession, current_user, student: Student, change_id, reason: str
) -> dict:
    """Undo a cambio de RVOE: the old plan, its groups and the subjects it had in
    course come back; what the change created in the new plan goes away. Refused
    while the new plan holds captured grades (they are not the change's to erase:
    each one is corrected first, leaving it empty). Charges without payment are cancelled;
    those with a payment stay on the student's account for Tesorería. Caller commits."""
    change = await session.get(PlanChange, change_id)
    if change is None or change.student_id != student.id:
        raise HTTPException(status_code=404, detail="Cambio de RVOE no encontrado")
    if change.reverted_at is not None:
        raise HTTPException(status_code=409, detail="Ese cambio de RVOE ya fue revertido")
    new_plan = await session.get(StudentPlanEnrollment, change.to_plan_enrollment_id)
    active = await active_plan_changes(session, [change.to_plan_enrollment_id])
    if new_plan is None or not active or active[-1].id != change.id:
        raise HTTPException(status_code=409, detail="Hay un cambio de RVOE posterior; revierta primero ese")
    if new_plan.status != PlanEnrollmentStatus.inscrito:
        raise HTTPException(status_code=409, detail="Hay un cambio de RVOE posterior; revierta primero ese")
    detail = change.detail
    old_plan = await session.get(StudentPlanEnrollment, change.from_plan_enrollment_id)
    if old_plan is None:
        raise HTTPException(status_code=409, detail="El plan anterior ya no existe")
    since = datetime.fromisoformat(detail["started_at"]) if detail.get("started_at") else None

    created = (
        await session.exec(
            select(SubjectEnrollment, Group, PlanSubject)
            .join(GroupEnrollment, GroupEnrollment.id == SubjectEnrollment.group_enrollment_id)
            .join(Group, Group.id == GroupEnrollment.group_id)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .where(GroupEnrollment.plan_enrollment_id == new_plan.id)
        )
    ).all()
    if since is not None:  # came back to a plan with history: that history stays
        created = [row for row in created if row[0].created_at >= since]
    regular = [row for row in created if recognition_kind(row[1].code) is None]
    captured = set(
        (
            await session.exec(
                select(Grade.subject_enrollment_id).where(
                    Grade.subject_enrollment_id.in_([se.id for se, *_ in regular] or [uuid.uuid4()])  # type: ignore[attr-defined]
                )
            )
        ).all()
    )
    graded = [ps.name for se, _, ps in regular if se.final_grade is not None or se.id in captured]
    if graded:
        raise HTTPException(
            status_code=409,
            detail="Ya tiene calificaciones en el plan nuevo: " + ", ".join(sorted(graded))
            + ". Con «Corregir» déjelas vacías antes de revertir.",
        )
    for se, *_ in created:
        await _delete_enrollment(session, se)
    await session.flush()

    # the group enrollments of the change, their charges with them
    group_enrollments = (
        await session.exec(select(GroupEnrollment).where(GroupEnrollment.plan_enrollment_id == new_plan.id))
    ).all()
    cancelled = kept = 0
    for ge in group_enrollments:
        if since is not None and ge.created_at < since:
            continue
        if (await session.exec(
            select(SubjectEnrollment.id).where(SubjectEnrollment.group_enrollment_id == ge.id)
        )).first():
            continue
        for charge in (await session.exec(select(Charge).where(Charge.group_enrollment_id == ge.id))).all():
            charge.group_enrollment_id = None
            if charge.status == ChargeStatus.pendiente:
                charge.status = ChargeStatus.cancelado
                cancelled += 1
                for fee in (await session.exec(
                    select(Charge).where(
                        Charge.source_charge_id == charge.id, Charge.status == ChargeStatus.pendiente
                    )
                )).all():
                    fee.status = ChargeStatus.cancelado
                    session.add(fee)
            elif charge.status != ChargeStatus.cancelado:
                kept += 1
            session.add(charge)
        await session.flush()
        await session.delete(ge)
    await session.flush()
    left = (
        await session.exec(select(GroupEnrollment.id).where(GroupEnrollment.plan_enrollment_id == new_plan.id))
    ).first()
    change.reverted_at = utcnow()
    change.reverted_by = current_user.email
    change.revert_reason = reason.strip()[:255]
    session.add(change)
    if left is None and detail.get("new_plan_created", True):
        # the changes already reverted that mention it let go of it
        for mention in (
            await session.exec(
                select(PlanChange).where(
                    (PlanChange.to_plan_enrollment_id == new_plan.id)
                    | (PlanChange.from_plan_enrollment_id == new_plan.id)
                )
            )
        ).all():
            if mention.to_plan_enrollment_id == new_plan.id:
                mention.to_plan_enrollment_id = None
            if mention.from_plan_enrollment_id == new_plan.id:
                mention.from_plan_enrollment_id = None
            session.add(mention)
        await session.flush()
        await session.delete(new_plan)
    else:
        new_plan.status = PlanEnrollmentStatus.baja
        session.add(new_plan)

    old_plan.status = PlanEnrollmentStatus.inscrito
    session.add(old_plan)
    for ge_id in detail.get("closed_group_enrollment_ids", []):
        ge = await session.get(GroupEnrollment, uuid.UUID(ge_id))
        if ge is not None:
            ge.status = GroupEnrollmentStatus.activa
            session.add(ge)
    for se_id in detail.get("dropped_subject_enrollment_ids", []):
        se = await session.get(SubjectEnrollment, uuid.UUID(se_id))
        if se is not None and se.status == SubjectEnrollmentStatus.baja:
            se.status = SubjectEnrollmentStatus.cursando
            session.add(se)
    campus_id = detail.get("from_campus_id")
    if campus_id is None:  # a change recorded before these details were kept
        old_group = (
            await session.exec(
                select(Group)
                .join(GroupEnrollment, GroupEnrollment.group_id == Group.id)
                .where(GroupEnrollment.plan_enrollment_id == old_plan.id, ~internal_group_clause())
                .order_by(GroupEnrollment.created_at.desc())  # type: ignore[attr-defined]
            )
        ).first()
        campus_id = str(old_group.campus_id) if old_group else str(student.campus_id)
    if str(student.campus_id) != campus_id:
        student.campus_id = uuid.UUID(campus_id)
        session.add(student)
    audit.record(
        session, actor=current_user.email, action=PLAN_CHANGE_REVERTED_ACTION,
        entity="plan_change", entity_id=str(change.id),
        detail=json.dumps({
            "reason": reason.strip(), "removed_subjects": [ps.code for _, _, ps in created],
            "cancelled_charges": cancelled, "paid_charges_kept": kept,
        }, ensure_ascii=False),
    )
    await session.flush()
    return {"restored_plan_version_id": str(old_plan.plan_version_id),
            "cancelled_charges": cancelled, "paid_charges_kept": kept}
