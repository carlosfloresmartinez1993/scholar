"""Enrollment orchestration: create a student and enroll them into a group as one
reusable unit, shared by the single-student route (RT-09) and bulk cohort intake.
Neither function commits — the caller owns the transaction boundary (one commit per
request, or one per row for bulk so a bad row never rolls back the good ones)."""
import re

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    FolioCounter,
    Group,
    GroupEnrollment,
    GroupEnrollmentKind,
    GroupEnrollmentStatus,
    GroupSubject,
    Institution,
    PlanSubject,
    Student,
    StudentCreate,
    StudentRelative,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    UserRole,
)
from app.services import audit
from app.services.academics import (
    check_prerequisites,
    get_or_create_plan_enrollment,
    require_operable_rvoe,
)
from app.services.treasury import generate_enrollment_charges

MAX_MATRICULA_LEN = 32  # Student.enrollment_number column width
MAX_FOLIO_NUMBER = 2_147_483_647  # folio_counters.last_number is an int4


async def create_student_core(
    session: AsyncSession,
    institution: Institution,
    body: StudentCreate,
    actor: str,
    *,
    enrollment_number: str | None = None,
) -> Student:
    """Create a student with a row-locked matrícula (RT-09). Rejects a duplicate
    CURP. Caller commits.

    enrollment_number keeps an existing matrícula (a servoescolar.mx migration)
    instead of allocating one; it must be unique within the institution."""
    dup = (
        await session.exec(
            select(Student).where(
                Student.institution_id == institution.id, Student.curp == body.curp
            )
        )
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="Ya existe un alumno con esa CURP (RT-09)")
    prefix = institution.short_name[:4].upper()
    if enrollment_number is not None:
        return await _create_with_matricula(
            session, institution, body, actor, enrollment_number.strip().upper(), prefix
        )
    # matrícula: institution prefix + per-institution sequence. The counter is
    # row-locked once it exists; the FIRST-ever create has no row to lock, so two
    # concurrent first creates can both seed it and collide on the unique
    # constraint. Do the allocation in a SAVEPOINT and retry once: the loser's
    # savepoint rolls back and the retry finds + locks the winner's counter.
    student: Student | None = None
    for attempt in range(2):
        try:
            async with session.begin_nested():
                counter = (
                    await session.exec(
                        select(FolioCounter)
                        .where(
                            FolioCounter.institution_id == institution.id,
                            FolioCounter.series == "MAT",
                        )
                        .with_for_update()
                    )
                ).first()
                if counter is None:
                    # Seed from the highest number across matrículas of OUR OWN
                    # series (prefix + digits, parsed whole so 7+ digit ones don't
                    # reuse a number). A matrícula kept from an import (Servo's are
                    # bare numbers like 20210123) is not one of ours and must not
                    # shift the series.
                    existing = (
                        await session.exec(
                            select(Student.enrollment_number).where(
                                Student.institution_id == institution.id
                            )
                        )
                    ).all()
                    numbers = [
                        int(m.group(1))
                        for n in existing
                        if (m := re.fullmatch(rf"{re.escape(prefix)}(\d+)", n or ""))
                    ]
                    counter = FolioCounter(
                        institution_id=institution.id, series="MAT",
                        last_number=max(numbers, default=0),
                    )
                counter.last_number += 1
                session.add(counter)
                student = Student(
                    **body.model_dump(exclude={"relatives"}),
                    institution_id=institution.id,
                    enrollment_number=f"{prefix}{counter.last_number:06d}",
                )
                session.add(student)
                await session.flush()
                for relative in body.relatives:
                    session.add(
                        StudentRelative(student_id=student.id, **relative.model_dump())
                    )
            break
        except IntegrityError as e:
            # classify the violated constraint (portable across SQLite/Postgres:
            # both name the column/constraint in the message)
            msg = str(e.orig).lower()
            if "curp" in msg:  # concurrent duplicate CURP slipped past the pre-check
                raise HTTPException(
                    status_code=409, detail="Ya existe un alumno con esa CURP (RT-09)"
                ) from e
            # retryable first-use race: the matrícula itself OR its folio counter
            # (uq_folio_series) — a concurrent first create seeded the counter first
            retryable = any(k in msg for k in ("matricula", "enrollment_number", "folio"))
            if not retryable:
                raise  # unknown constraint (FK, etc.) — don't swallow as retryable
            if attempt == 1:
                raise HTTPException(
                    status_code=409, detail="No se pudo asignar matrícula; reintente"
                ) from e
            # else: allocation race — loop retries
    assert student is not None
    audit.record(session, actor=actor, action="student.created",
                 entity="student", entity_id=str(student.id), detail=student.curp)
    await session.flush()
    return student


async def _create_with_matricula(
    session: AsyncSession,
    institution: Institution,
    body: StudentCreate,
    actor: str,
    enrollment_number: str,
    prefix: str,
) -> Student:
    """Create keeping a given matrícula. If it looks like one of ours
    (prefix + digits) the MAT counter is pushed past it so later allocations
    can't collide with it."""
    if not enrollment_number:
        raise HTTPException(status_code=422, detail="Matrícula vacía")
    if len(enrollment_number) > MAX_MATRICULA_LEN:
        # the column is VARCHAR(32) and a table model skips pydantic validation,
        # so without this a mis-mapped column would be a DB error mid-batch
        raise HTTPException(
            status_code=422,
            detail=f"Matrícula demasiado larga (máx. {MAX_MATRICULA_LEN} caracteres)",
        )
    dup = (
        await session.exec(
            select(Student).where(
                Student.institution_id == institution.id,
                Student.enrollment_number == enrollment_number,
            )
        )
    ).first()
    if dup:
        raise HTTPException(
            status_code=409, detail=f"Ya existe un alumno con la matrícula {enrollment_number}"
        )
    try:
        async with session.begin_nested():
            if m := re.fullmatch(rf"{re.escape(prefix)}(\d+)", enrollment_number):
                number = int(m.group(1))
                counter = (
                    await session.exec(
                        select(FolioCounter)
                        .where(
                            FolioCounter.institution_id == institution.id,
                            FolioCounter.series == "MAT",
                        )
                        .with_for_update()
                    )
                ).first()
                if counter is None:
                    # create the series here instead of leaving it to the next
                    # allocation's lazy seed, so both paths agree on what counts
                    # as one of ours (and the int4 guard below always applies)
                    counter = FolioCounter(
                        institution_id=institution.id, series="MAT", last_number=0
                    )
                if counter.last_number < number <= MAX_FOLIO_NUMBER:
                    counter.last_number = number
                session.add(counter)
            student = Student(
                **body.model_dump(exclude={"relatives"}),
                institution_id=institution.id,
                enrollment_number=enrollment_number,
            )
            session.add(student)
            await session.flush()
            for relative in body.relatives:
                session.add(StudentRelative(student_id=student.id, **relative.model_dump()))
    except IntegrityError as e:
        msg = str(e.orig).lower()
        if "curp" in msg:
            raise HTTPException(
                status_code=409, detail="Ya existe un alumno con esa CURP (RT-09)"
            ) from e
        if "matricula" in msg or "enrollment_number" in msg:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un alumno con la matrícula {enrollment_number}",
            ) from e
        raise
    audit.record(session, actor=actor, action="student.created",
                 entity="student", entity_id=str(student.id),
                 detail=f"{student.curp} (matrícula conservada)")
    await session.flush()
    return student


async def enroll_student_core(
    session: AsyncSession,
    current_user,
    student: Student,
    group: Group,
    *,
    plan_subject_ids: list | None = None,
    override_prerequisites: bool = False,
    waive_enrollment_fee: bool = False,
) -> GroupEnrollment:
    """Enroll a student into a group in one act: plan enrollment (auto), subjects,
    seriación (RF-C07), inscripción/reinscripción, and auto-billing (RF-T02).
    Caller commits."""
    plan_subject_ids = plan_subject_ids or []
    # Servo keys inscripciones by (Ciclo, Plantel): a student can only enroll in a
    # group of their own campus.
    if student.campus_id != group.campus_id:
        raise HTTPException(
            status_code=409, detail="El alumno y el grupo pertenecen a planteles distintos"
        )
    await require_operable_rvoe(session, group.plan_version_id)  # RT-03
    plan_enrollment, plan_created = await get_or_create_plan_enrollment(
        session, student, group.plan_version_id, group.term_id
    )
    if plan_created:
        audit.record(
            session, actor=current_user.email, action="plan_enrollment.created",
            entity="plan_enrollment", entity_id=str(plan_enrollment.id),
            detail="auto (inscripción a grupo)",
        )
    dup = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.student_id == student.id,
                GroupEnrollment.group_id == group.id,
            )
        )
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="El alumno ya está inscrito en ese grupo")

    group_subjects = (
        await session.exec(select(GroupSubject).where(GroupSubject.group_id == group.id))
    ).all()
    if plan_subject_ids:
        wanted = set(plan_subject_ids)
        group_subjects = [gs for gs in group_subjects if gs.plan_subject_id in wanted]
        if len(group_subjects) != len(wanted):
            raise HTTPException(status_code=400, detail="Alguna materia no se imparte en el grupo")

    if not override_prerequisites:
        for gs in group_subjects:
            missing = await check_prerequisites(session, student.id, gs.plan_subject_id)
            if missing:
                subject = await session.get(PlanSubject, gs.plan_subject_id)
                raise HTTPException(
                    status_code=409,
                    detail=f"Seriación no cumplida para {subject.name if subject else gs.plan_subject_id}",
                )
    elif current_user.role not in (UserRole.servicios_escolares, UserRole.admin_sistema) and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Solo Servicios Escolares puede omitir seriación")

    previous = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.plan_enrollment_id == plan_enrollment.id
            )
        )
    ).first()
    kind = GroupEnrollmentKind.reinscripcion if previous else GroupEnrollmentKind.inscripcion

    enrollment = GroupEnrollment(
        student_id=student.id, group_id=group.id,
        plan_enrollment_id=plan_enrollment.id, kind=kind,
    )
    session.add(enrollment)
    await session.flush()
    for gs in group_subjects:
        attempts = (
            await session.exec(
                select(SubjectEnrollment)
                .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
                .where(
                    SubjectEnrollment.student_id == student.id,
                    GroupSubject.plan_subject_id == gs.plan_subject_id,
                )
            )
        ).all()
        session.add(
            SubjectEnrollment(
                group_enrollment_id=enrollment.id, group_subject_id=gs.id,
                student_id=student.id, attempt_number=len(attempts) + 1,
            )
        )
    audit.record(
        session, actor=current_user.email, action="group_enrollment.created",
        entity="group_enrollment", entity_id=str(enrollment.id),
        detail=f"grupo {group.code}, {len(group_subjects)} materias"
        + (" (seriación omitida)" if override_prerequisites else ""),
    )
    # Single "Inscribir" also bills the cuatrimestre (RF-T02): enrollment fee +
    # monthly colegiaturas. Best-effort — skipped if the tabulador isn't set up.
    generated = await generate_enrollment_charges(
        session, student=student, group=group, enrollment=enrollment, kind=kind,
        created_by=current_user.id, waive_enrollment_fee=waive_enrollment_fee,
    )
    if generated:
        audit.record(
            session, actor=current_user.email, action="charges.generated",
            entity="group_enrollment", entity_id=str(enrollment.id),
            detail=f"{len(generated)} cargos del cuatrimestre",
        )
    return enrollment


async def add_subjects_core(
    session: AsyncSession,
    current_user,
    student: Student,
    group: Group,
    *,
    plan_subject_ids: list,
    override_prerequisites: bool = False,
) -> list[SubjectEnrollment]:
    """Add plan subjects to a student already enrolled in the group, at any point of
    the term (a materia missing from the plan or the group, a late addition, a
    recursamiento). Subjects of the group's plan up to the group's cuatrimestre are
    accepted, never later ones; an earlier one already failed becomes a
    recursamiento (next attempt). One the group does not teach yet is added to it
    (teacher unassigned). No new group enrollment, so
    nothing is billed. Caller commits."""
    if not plan_subject_ids:
        raise HTTPException(status_code=400, detail="Seleccione al menos una materia")
    enrollment = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.student_id == student.id,
                GroupEnrollment.group_id == group.id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
            )
        )
    ).first()
    if enrollment is None:
        raise HTTPException(status_code=404, detail="El alumno no está inscrito en ese grupo")
    if override_prerequisites and not (
        current_user.is_superuser
        or current_user.role in (UserRole.servicios_escolares, UserRole.admin_sistema)
    ):
        raise HTTPException(status_code=403, detail="Solo Servicios Escolares puede omitir seriación")

    subjects = (
        await session.exec(
            select(PlanSubject).where(PlanSubject.id.in_(set(plan_subject_ids)))  # type: ignore[attr-defined]
        )
    ).all()
    if len(subjects) != len(set(plan_subject_ids)) or any(
        s.plan_version_id != group.plan_version_id for s in subjects
    ):
        raise HTTPException(status_code=400, detail="Alguna materia no pertenece al plan del grupo")

    later = [s.name for s in subjects if s.period_number > group.period_number]
    if later:
        raise HTTPException(
            status_code=409,
            detail=f"{', '.join(later)}: es de un cuatrimestre posterior al del grupo",
        )

    added = []
    for subject in sorted(subjects, key=lambda s: (s.period_number, s.code)):
        attempts = (
            await session.exec(
                select(SubjectEnrollment, GroupSubject)
                .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
                .where(
                    SubjectEnrollment.student_id == student.id,
                    GroupSubject.plan_subject_id == subject.id,
                )
            )
        ).all()
        for attempt, gs in attempts:
            if attempt.group_enrollment_id == enrollment.id:
                raise HTTPException(
                    status_code=409, detail=f"{subject.name} ya está inscrita en este grupo"
                )
            if attempt.status == SubjectEnrollmentStatus.aprobada:
                raise HTTPException(status_code=409, detail=f"{subject.name} ya está aprobada")
            if attempt.status == SubjectEnrollmentStatus.cursando:
                raise HTTPException(
                    status_code=409, detail=f"{subject.name} ya se está cursando en otro grupo"
                )
        if not override_prerequisites and await check_prerequisites(session, student.id, subject.id):
            raise HTTPException(status_code=409, detail=f"Seriación no cumplida para {subject.name}")

        group_subject = (
            await session.exec(
                select(GroupSubject).where(
                    GroupSubject.group_id == group.id, GroupSubject.plan_subject_id == subject.id
                )
            )
        ).first()
        if group_subject is None:
            group_subject = GroupSubject(group_id=group.id, plan_subject_id=subject.id)
            session.add(group_subject)
            await session.flush()
        subject_enrollment = SubjectEnrollment(
            group_enrollment_id=enrollment.id, group_subject_id=group_subject.id,
            student_id=student.id, attempt_number=len(attempts) + 1,
        )
        session.add(subject_enrollment)
        added.append(subject_enrollment)

    audit.record(
        session, actor=current_user.email, action="subject_enrollment.added",
        entity="group_enrollment", entity_id=str(enrollment.id),
        detail=f"grupo {group.code}: " + ", ".join(s.code for s in subjects)
        + (" (seriación omitida)" if override_prerequisites else ""),
    )
    await session.flush()
    return added
