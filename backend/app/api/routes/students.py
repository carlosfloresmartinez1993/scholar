"""Students: registry by CURP (RT-09), plan enrollment (fixes the RVOE, RF-C04),
group/subject enrollment with seriación (RF-C07) and RVOE blocking (RT-03),
and the SEP statistics export (RT-10)."""
import csv
import io
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.api.deps import AnyStaff, ServiciosEscolares, SessionDep
from app.api.routes.catalog import get_default_institution
from app.models import (
    Group,
    GroupEnrollment,
    GroupEnrollmentCreate,
    GroupEnrollmentKind,
    GroupEnrollmentPublic,
    GroupSubject,
    PlanEnrollmentCreate,
    PlanEnrollmentPublic,
    PlanSubject,
    PlanVersion,
    Program,
    Rvoe,
    Student,
    StudentCreate,
    StudentPlanEnrollment,
    StudentPublic,
    StudentUpdate,
    SubjectEnrollment,
    SubjectEnrollmentPublic,
    Term,
    UserRole,
)
from app.services import audit
from app.services.academics import (
    active_plan_enrollment,
    check_prerequisites,
    require_operable_rvoe,
)

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
async def list_students(
    session: SessionDep,
    _: AnyStaff,
    q: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[StudentPublic]:
    query = select(Student).order_by(Student.full_name).limit(min(limit, 500)).offset(offset)
    if q:
        like = f"%{q.upper()}%"
        query = query.where(
            (Student.curp.like(like))  # type: ignore[attr-defined]
            | (Student.full_name.ilike(f"%{q}%"))  # type: ignore[attr-defined]
            | (Student.enrollment_number.like(like))  # type: ignore[attr-defined]
        )
    if status:
        query = query.where(Student.status == status)
    return (await session.exec(query)).all()


@router.post("", status_code=201)
async def create_student(
    session: SessionDep, current_user: ServiciosEscolares, body: StudentCreate
) -> StudentPublic:
    institution = await get_default_institution(session)
    dup = (
        await session.exec(
            select(Student).where(
                Student.institution_id == institution.id, Student.curp == body.curp
            )
        )
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="Ya existe un alumno con esa CURP (RT-09)")
    # matrícula: YY + sequential
    count = len((await session.exec(select(Student.id))).all())
    enrollment_number = f"{institution.short_name[:4].upper()}{count + 1:06d}"
    student = Student(
        **body.model_dump(), institution_id=institution.id, enrollment_number=enrollment_number
    )
    session.add(student)
    audit.record(session, actor=current_user.email, action="student.created",
                 entity="student", entity_id=str(student.id), detail=student.curp)
    await session.commit()
    await session.refresh(student)
    return student


@router.get("/{student_id}")
async def get_student(session: SessionDep, _: AnyStaff, student_id: uuid.UUID) -> StudentPublic:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return student


@router.patch("/{student_id}")
async def update_student(
    session: SessionDep,
    current_user: ServiciosEscolares,
    student_id: uuid.UUID,
    body: StudentUpdate,
) -> StudentPublic:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    changes = body.model_dump(exclude_unset=True)
    old = {k: str(getattr(student, k)) for k in changes}
    for k, v in changes.items():
        setattr(student, k, v)
    session.add(student)
    audit.record(session, actor=current_user.email, action="student.updated",
                 entity="student", entity_id=str(student_id),
                 detail="; ".join(f"{k}: {old[k]} -> {v}" for k, v in changes.items()))
    await session.commit()
    await session.refresh(student)
    return student


# --- Plan enrollment (RF-C04) ---------------------------------------------------

@router.get("/{student_id}/plan-enrollments")
async def list_plan_enrollments(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> list[PlanEnrollmentPublic]:
    return (
        await session.exec(
            select(StudentPlanEnrollment).where(StudentPlanEnrollment.student_id == student_id)
        )
    ).all()


@router.post("/plan-enrollments", status_code=201)
async def enroll_in_plan(
    session: SessionDep, current_user: ServiciosEscolares, body: PlanEnrollmentCreate
) -> PlanEnrollmentPublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    await require_operable_rvoe(session, body.plan_version_id)  # RT-03
    if await session.get(Term, body.start_term_id) is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    dup = (
        await session.exec(
            select(StudentPlanEnrollment).where(
                StudentPlanEnrollment.student_id == body.student_id,
                StudentPlanEnrollment.plan_version_id == body.plan_version_id,
            )
        )
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="El alumno ya está inscrito en ese plan")
    enrollment = StudentPlanEnrollment(**body.model_dump())
    session.add(enrollment)
    audit.record(session, actor=current_user.email, action="plan_enrollment.created",
                 entity="plan_enrollment", entity_id=str(enrollment.id))
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


# --- Group + subject enrollment (RF-C07, RT-03) ------------------------------------

@router.get("/{student_id}/group-enrollments")
async def list_group_enrollments(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> list[GroupEnrollmentPublic]:
    return (
        await session.exec(
            select(GroupEnrollment).where(GroupEnrollment.student_id == student_id)
        )
    ).all()


@router.post("/group-enrollments", status_code=201)
async def enroll_in_group(
    session: SessionDep, current_user: ServiciosEscolares, body: GroupEnrollmentCreate
) -> GroupEnrollmentPublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    await require_operable_rvoe(session, group.plan_version_id)  # RT-03
    plan_enrollment = await active_plan_enrollment(session, student, group.plan_version_id)

    dup = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.student_id == body.student_id,
                GroupEnrollment.group_id == body.group_id,
            )
        )
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="El alumno ya está inscrito en ese grupo")

    # subjects: all of the group's, or the requested subset
    group_subjects = (
        await session.exec(select(GroupSubject).where(GroupSubject.group_id == group.id))
    ).all()
    if body.plan_subject_ids:
        wanted = set(body.plan_subject_ids)
        group_subjects = [gs for gs in group_subjects if gs.plan_subject_id in wanted]
        if len(group_subjects) != len(wanted):
            raise HTTPException(status_code=400, detail="Alguna materia no se imparte en el grupo")

    # RF-C07: seriación
    if not body.override_prerequisites:
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

    # kind: reinscripción if the student already had a group enrollment in this plan
    previous = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.plan_enrollment_id == plan_enrollment.id
            )
        )
    ).first()
    kind = GroupEnrollmentKind.reinscripcion if previous else body.kind

    enrollment = GroupEnrollment(
        student_id=student.id,
        group_id=group.id,
        plan_enrollment_id=plan_enrollment.id,
        kind=kind,
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
                group_enrollment_id=enrollment.id,
                group_subject_id=gs.id,
                student_id=student.id,
                attempt_number=len(attempts) + 1,
            )
        )
    audit.record(
        session, actor=current_user.email, action="group_enrollment.created",
        entity="group_enrollment", entity_id=str(enrollment.id),
        detail=f"grupo {group.code}, {len(group_subjects)} materias"
        + (" (seriación omitida)" if body.override_prerequisites else ""),
    )
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.get("/{student_id}/subject-enrollments")
async def list_subject_enrollments(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> list[SubjectEnrollmentPublic]:
    return (
        await session.exec(
            select(SubjectEnrollment).where(SubjectEnrollment.student_id == student_id)
        )
    ).all()


# --- SEP export (RT-10) --------------------------------------------------------------

@router.get("/exports/sep")
async def sep_export(
    session: SessionDep, _: ServiciosEscolares, term_id: uuid.UUID
) -> StreamingResponse:
    """CSV of enrolled/re-enrolled students by program and plan for a term."""
    term = await session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    result = await session.exec(
        select(Student, GroupEnrollment, Group, PlanVersion, Rvoe, Program)
        .join(GroupEnrollment, GroupEnrollment.student_id == Student.id)
        .join(Group, Group.id == GroupEnrollment.group_id)
        .join(PlanVersion, PlanVersion.id == Group.plan_version_id)
        .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
        .join(Program, Program.id == Rvoe.program_id)
        .where(Group.term_id == term_id)
        .order_by(Program.name, Student.full_name)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["CURP", "Matricula", "Nombre", "Programa", "Nivel", "RVOE", "Modalidad",
         "PlanVersion", "Grupo", "TipoInscripcion", "Ciclo"]
    )
    for student, enrollment, group, plan, rvoe, program in result.all():
        writer.writerow(
            [student.curp, student.enrollment_number, student.full_name, program.name,
             program.level, rvoe.agreement_number, rvoe.modality, plan.version_label,
             group.code, enrollment.kind, term.name]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sep_{term.name}.csv"'},
    )
