"""Students: registry by CURP (RT-09), plan enrollment (fixes the RVOE, RF-C04),
group/subject enrollment with seriación (RF-C07) and RVOE blocking (RT-03),
and the SEP statistics export (RT-10)."""
import asyncio
import csv
import io
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.api.deps import AnyStaff, ServiciosEscolares, SessionDep
from app.api.routes.catalog import get_default_institution
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models import (
    BulkIntakeError,
    BulkIntakeIn,
    BulkIntakeResult,
    Group,
    GroupEnrollment,
    GroupEnrollmentCreate,
    GroupEnrollmentPublic,
    GroupEnrollmentStatus,
    PlanEnrollmentCreate,
    PlanEnrollmentPublic,
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
)
from app.services import audit, calendar
from app.services.academics import require_operable_rvoe
from app.services.enrollment import create_student_core, enroll_student_core
from app.services.promotion import promote_cycle

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
async def list_students(
    session: SessionDep,
    _: AnyStaff,
    q: str | None = None,
    status: str | None = None,
    campus_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[StudentPublic]:
    query = select(Student).order_by(Student.full_name).limit(min(limit, 500)).offset(offset)
    if campus_id:
        query = query.where(Student.campus_id == campus_id)
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
    student = await create_student_core(session, institution, body, current_user.email)
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
    enrollment = await enroll_student_core(
        session, current_user, student, group,
        plan_subject_ids=body.plan_subject_ids,
        override_prerequisites=body.override_prerequisites,
        waive_enrollment_fee=body.waive_enrollment_fee,
    )
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.post("/bulk-intake", status_code=201)
async def bulk_intake(
    session: SessionDep, current_user: ServiciosEscolares, body: BulkIntakeIn
) -> BulkIntakeResult:
    """Onboard a whole cohort of NEW students into one group: create + enroll +
    auto-bill each row. Existing CURPs are rejected (enroll them via the group
    flow). Each row commits on its own, so a bad row never rolls back the good
    ones; failures come back with a reason."""
    institution = await get_default_institution(session)
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    enrolled = 0
    errors: list[BulkIntakeError] = []
    seen: set[str] = set()
    for i, row in enumerate(body.rows, start=1):
        curp = row.curp.strip().upper()
        if curp in seen:
            errors.append(BulkIntakeError(row=i, curp=curp, detail="CURP duplicada en el archivo"))
            continue
        seen.add(curp)
        try:
            # SAVEPOINT per row: a bad row rolls back only its own work, and the
            # shared objects (institution/group) stay live — no per-row commit that
            # would expire them mid-loop. One commit at the end persists the good rows.
            async with session.begin_nested():
                student_in = StudentCreate(
                    curp=curp, full_name=row.full_name.strip(),
                    email=row.email.strip(), campus_id=group.campus_id,
                )
                student = await create_student_core(
                    session, institution, student_in, current_user.email
                )
                await enroll_student_core(
                    session, current_user, student, group,
                    override_prerequisites=body.override_prerequisites,
                    waive_enrollment_fee=body.waive_enrollment_fee,
                )
            enrolled += 1
        except IntegrityError:
            # concurrent request won a uq_student_curp / uq_student_matricula race;
            # the SAVEPOINT rolled this row back, so the good rows are untouched
            errors.append(BulkIntakeError(
                row=i, curp=curp,
                detail="Conflicto de integridad (CURP o matrícula duplicada)",
            ))
        except (HTTPException, ValidationError, ValueError) as e:
            detail = e.detail if isinstance(e, HTTPException) else str(e)
            errors.append(BulkIntakeError(row=i, curp=curp, detail=detail))
    audit.record(
        session, actor=current_user.email, action="bulk_intake.completed",
        entity="group", entity_id=str(group.id),
        detail=f"{enrolled} inscritos, {len(errors)} errores",
    )
    await session.commit()
    return BulkIntakeResult(enrolled=enrolled, errors=errors)


@router.post("/promote-cycle")
async def promote_cycle_endpoint(
    session: SessionDep, current_user: ServiciosEscolares, dry_run: bool = True
) -> dict:
    """Preview (dry_run=true, default) or run cycle promotion: enroll + bill each
    linked next-term group's passing, continuing students (reinscripción). Scoped
    to the caller's institution (the cron runs it globally)."""
    institution = await get_default_institution(session)
    return await promote_cycle(
        session, current_user, institution_id=institution.id, dry_run=dry_run
    )


@router.get("/{student_id}/subject-enrollments")
async def list_subject_enrollments(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> list[SubjectEnrollmentPublic]:
    return (
        await session.exec(
            select(SubjectEnrollment).where(SubjectEnrollment.student_id == student_id)
        )
    ).all()


# --- Calendar schedule (calendar.inue.online) -----------------------------------------

@router.get("/{student_id}/calendar")
async def student_calendar(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> dict:
    """Published schedule blocks of the student's active groups, read from the
    calendar system via each Group.calendar_group_id link."""
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    groups = (
        await session.exec(
            select(Group)
            .join(GroupEnrollment, GroupEnrollment.group_id == Group.id)
            .join(Term, Term.id == Group.term_id)
            .where(
                GroupEnrollment.student_id == student_id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
                Term.is_open == True,  # noqa: E712 - only current terms, not past/future ones
            )
        )
    ).all()
    linked_groups = [g for g in groups if g.calendar_group_id]
    if not linked_groups:
        return {"items": [], "linked": False, "errors": []}

    async def fetch(group: Group) -> list[dict] | None:
        try:
            return await calendar.get_schedule(group.calendar_group_id)
        except HTTPException:
            return None  # one bad link/upstream error must not hide the other groups

    results = await asyncio.gather(*(fetch(group) for group in linked_groups))
    items: list[dict] = []
    errors: list[str] = []
    for group, blocks in zip(linked_groups, results):
        if blocks is None:
            errors.append(group.code)
            continue
        items.extend({"group_code": group.code, **block} for block in blocks)
    return {"items": items, "linked": True, "errors": errors}


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
