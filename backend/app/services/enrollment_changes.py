"""Bajas de materia y cambio de grupo de un alumno ya inscrito.

- Baja de materia: the subject enrollment is kept (history, audit) with status
  «baja»; it leaves the group's lists (calificaciones, asistencia, actas) and the
  kárdex, and does not count as an attempt. Only a subject still in course (no
  final grade) can be dropped. If nothing is left in the group, the student's
  enrollment in the group is closed (baja) too.
- Cambio de grupo: within the same term and plan, the subjects in course move to
  the destination group with what was captured so far (the evaluation scheme is
  per plan subject, so grades stay valid). The old group enrollment is closed and
  its charges follow the student, so nothing is billed twice. A group of another
  campus moves the student's campus (e.g. presencial → online).

No schema change. Neither function commits."""
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Charge,
    Grade,
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    GroupSubject,
    PlanSubject,
    Student,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
)
from app.services import audit
from app.services.academics import recognition_kind


async def _close_if_empty(session: AsyncSession, enrollment: GroupEnrollment) -> bool:
    remaining = (
        await session.exec(
            select(SubjectEnrollment.id).where(
                SubjectEnrollment.group_enrollment_id == enrollment.id,
                SubjectEnrollment.status != SubjectEnrollmentStatus.baja,
            )
        )
    ).first()
    if remaining is None and enrollment.status == GroupEnrollmentStatus.activa:
        enrollment.status = GroupEnrollmentStatus.baja
        session.add(enrollment)
        return True
    return False


async def drop_subjects(
    session: AsyncSession, user, subject_enrollment_ids: list, reason: str = ""
) -> list[SubjectEnrollment]:
    """Baja de una o varias materias (del mismo alumno)."""
    if not subject_enrollment_ids:
        raise HTTPException(status_code=400, detail="Seleccione al menos una materia")
    dropped: list[SubjectEnrollment] = []
    labels: list[str] = []
    group_enrollments: dict = {}
    student_id = None
    for se_id in dict.fromkeys(subject_enrollment_ids):
        se = await session.get(SubjectEnrollment, se_id)
        if se is None:
            raise HTTPException(status_code=404, detail="Materia no encontrada")
        if student_id is not None and se.student_id != student_id:
            raise HTTPException(status_code=400, detail="Las materias deben ser del mismo alumno")
        student_id = se.student_id
        gs = await session.get(GroupSubject, se.group_subject_id)
        group = await session.get(Group, gs.group_id) if gs else None
        subject = await session.get(PlanSubject, gs.plan_subject_id) if gs else None
        name = subject.name if subject else str(se.id)
        if group is not None and recognition_kind(group.code):
            raise HTTPException(
                status_code=409, detail=f"{name}: es un reconocimiento (EQ/REV/CONV), no una clase"
            )
        if se.status == SubjectEnrollmentStatus.baja:
            raise HTTPException(status_code=409, detail=f"{name} ya está dada de baja")
        if se.status != SubjectEnrollmentStatus.cursando or se.final_grade is not None:
            raise HTTPException(
                status_code=409, detail=f"{name} ya tiene calificación final; no se puede dar de baja"
            )
        se.status = SubjectEnrollmentStatus.baja
        session.add(se)
        dropped.append(se)
        labels.append(f"{subject.code if subject else ''} ({group.code if group else ''})")
        ge = await session.get(GroupEnrollment, se.group_enrollment_id)
        if ge is not None:
            group_enrollments[ge.id] = ge
    await session.flush()
    closed = [ge for ge in group_enrollments.values() if await _close_if_empty(session, ge)]
    for se in dropped:
        audit.record(
            session, actor=user.email, action="subject_enrollment.dropped",
            entity="subject_enrollment", entity_id=str(se.id),
            detail=", ".join(labels) + (f" — {reason.strip()}" if reason.strip() else ""),
        )
    for ge in closed:
        audit.record(
            session, actor=user.email, action="group_enrollment.dropped",
            entity="group_enrollment", entity_id=str(ge.id),
            detail="sin materias en el grupo tras la baja",
        )
    await session.flush()
    return dropped


async def change_group(
    session: AsyncSession, user, student: Student, from_group: Group, to_group: Group,
    reason: str = "",
) -> GroupEnrollment:
    """Cambio de grupo dentro del mismo ciclo y plan."""
    if from_group.id == to_group.id:
        raise HTTPException(status_code=400, detail="Elija un grupo distinto")
    if recognition_kind(from_group.code) or recognition_kind(to_group.code):
        raise HTTPException(status_code=400, detail="Grupo no válido")
    if to_group.plan_version_id != from_group.plan_version_id:
        raise HTTPException(
            status_code=409,
            detail="El grupo destino es de otro plan; para cambiar de carrera o RVOE use «Cambio de RVOE»",
        )
    if to_group.term_id != from_group.term_id:
        raise HTTPException(status_code=409, detail="El grupo destino es de otro ciclo")
    if not to_group.is_active:
        raise HTTPException(status_code=409, detail="El grupo destino no está activo")
    old = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.student_id == student.id,
                GroupEnrollment.group_id == from_group.id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
            )
        )
    ).first()
    if old is None:
        raise HTTPException(status_code=404, detail="El alumno no está inscrito en ese grupo")

    moving = (
        await session.exec(
            select(SubjectEnrollment, GroupSubject, PlanSubject)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .where(
                SubjectEnrollment.group_enrollment_id == old.id,
                SubjectEnrollment.status == SubjectEnrollmentStatus.cursando,
            )
        )
    ).all()
    # moving down a cuatrimestre: nothing ahead of the destination's level. A group of
    # the same (or a later) cuatrimestre takes whatever the student had in course.
    later = []
    if to_group.period_number < from_group.period_number:
        later = [ps.name for _, _, ps in moving if ps.period_number > to_group.period_number]
    if later:
        raise HTTPException(
            status_code=409,
            detail=f"{', '.join(later)}: es de un cuatrimestre posterior al del grupo destino",
        )

    target = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.student_id == student.id,
                GroupEnrollment.group_id == to_group.id,
            )
        )
    ).first()
    if target is not None and target.status == GroupEnrollmentStatus.activa:
        raise HTTPException(status_code=409, detail="El alumno ya está inscrito en el grupo destino")
    if target is None:
        target = GroupEnrollment(
            student_id=student.id, group_id=to_group.id,
            plan_enrollment_id=old.plan_enrollment_id, kind=old.kind,
        )
    target.status = GroupEnrollmentStatus.activa
    session.add(target)
    await session.flush()

    for se, _, ps in moving:
        gs = (
            await session.exec(
                select(GroupSubject).where(
                    GroupSubject.group_id == to_group.id, GroupSubject.plan_subject_id == ps.id
                )
            )
        ).first()
        if gs is None:  # the destination group did not teach it yet
            gs = GroupSubject(group_id=to_group.id, plan_subject_id=ps.id)
            session.add(gs)
            await session.flush()
        # a row left there by an earlier stay in the destination group (baja)
        stale = (
            await session.exec(
                select(SubjectEnrollment).where(
                    SubjectEnrollment.group_enrollment_id == target.id,
                    SubjectEnrollment.group_subject_id == gs.id,
                )
            )
        ).first()
        if stale is not None:
            if stale.status != SubjectEnrollmentStatus.baja:
                raise HTTPException(status_code=409, detail=f"{ps.name} ya está en el grupo destino")
            # the dropped row (its baja stays in the audit log) frees the slot
            for grade in (
                await session.exec(select(Grade).where(Grade.subject_enrollment_id == stale.id))
            ).all():
                await session.delete(grade)
            await session.delete(stale)
            await session.flush()
        se.group_enrollment_id = target.id
        se.group_subject_id = gs.id
        session.add(se)

    old.status = GroupEnrollmentStatus.baja
    session.add(old)

    # charges follow the student (unless the destination already has its own)
    has_charges = (
        await session.exec(select(Charge.id).where(Charge.group_enrollment_id == target.id))
    ).first()
    if has_charges is None:
        for charge in (
            await session.exec(select(Charge).where(Charge.group_enrollment_id == old.id))
        ).all():
            charge.group_enrollment_id = target.id
            session.add(charge)

    if student.campus_id != to_group.campus_id:  # e.g. presencial -> online
        student.campus_id = to_group.campus_id
        session.add(student)

    audit.record(
        session, actor=user.email, action="group_enrollment.group_changed",
        entity="group_enrollment", entity_id=str(target.id),
        detail=f"{from_group.code} → {to_group.code}, {len(moving)} materias"
        + (f" — {reason.strip()}" if reason.strip() else ""),
    )
    await session.flush()
    return target
