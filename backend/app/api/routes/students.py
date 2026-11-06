"""Students: registry by CURP (RT-09), plan enrollment (fixes the RVOE, RF-C04),
group/subject enrollment with seriación (RF-C07) and RVOE blocking (RT-03),
and the SEP statistics export (RT-10)."""
import asyncio
import csv
import io
import uuid
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import select

from app.api.deps import (
    AnyStaff,
    CampusScope,
    ServiciosEscolares,
    SessionDep,
    can_read_debt,
    ensure_in_scope,
)
from app.api.routes.catalog import get_default_institution
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import (
    BulkIntakeError,
    BulkIntakeIn,
    BulkIntakeResult,
    Group,
    GroupEnrollment,
    GroupEnrollmentCreate,
    GroupEnrollmentSubjectsAdd,
    GroupEnrollmentPublic,
    GroupEnrollmentStatus,
    PlanEnrollmentCreate,
    RosterParseResult,
    PlanEnrollmentPublic,
    PlanVersion,
    Program,
    RelativeIn,
    RelativePublic,
    Rvoe,
    Student,
    StudentCreate,
    StudentPlanEnrollment,
    StudentPublic,
    StudentRelative,
    StudentUpdate,
    SubjectEnrollment,
    SubjectEnrollmentPublic,
    Term,
    User,
    UserPublic,
    WizardIntakeIn,
    WizardIntakeResult,
)
from app.services import audit, calendar, treasury
from app.services.academics import require_operable_rvoe
from app.services.email import send_email
from app.services.enrollment import add_subjects_core, create_student_core, enroll_student_core
from app.services.files import save_upload
from app.services.portal import credentials_email, grant_portal_access
from app.services.promotion import promote_cycle
from app.services.roster_import import normalize_date, normalize_sex, parse_roster

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
async def list_students(
    session: SessionDep,
    current_user: AnyStaff,
    scope: CampusScope,
    q: str | None = None,
    status: str | None = None,
    campus_id: uuid.UUID | None = None,
    carrera_of_plan_version_id: uuid.UUID | None = None,
    with_debt: bool = False,
    only_debtors: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[StudentPublic]:
    """`carrera_of_plan_version_id` keeps the students enrolled in any plan of that
    plan's carrera (any of its RVOE): enrolling into a group only offers students
    of the group's carrera. A new student always arrives with a group, through
    Inscripciones, so nobody is left out.

    `with_debt` adds each student's balance and overdue balance (two extra
    grouped queries for the whole page, not one per row); `only_debtors` keeps
    just those with an overdue balance — filtered inside the query, before the
    LIMIT, so it means "debtors in the institution" and not "debtors on this
    page".

    Both are gated: the list itself is AnyStaff, which includes docente, and a
    teacher can read a student's balance nowhere else in the system."""
    if (with_debt or only_debtors) and not can_read_debt(current_user):
        raise HTTPException(
            status_code=403, detail="No tienes acceso a la información de adeudo"
        )
    query = select(Student).order_by(Student.full_name).limit(min(limit, 500)).offset(offset)
    # Enforced campus scope: members only ever see their campuses' students.
    if scope is not None:
        query = query.where(Student.campus_id.in_(scope))  # type: ignore[attr-defined]
    if campus_id:
        ensure_in_scope(scope, campus_id)  # a ?campus_id outside membership is 403
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
    if carrera_of_plan_version_id:
        plan = await session.get(PlanVersion, carrera_of_plan_version_id)
        rvoe = plan and await session.get(Rvoe, plan.rvoe_id)
        if rvoe is None:
            raise HTTPException(status_code=404, detail="Plan de estudios no encontrado")
        query = query.where(
            Student.id.in_(  # type: ignore[attr-defined]
                select(StudentPlanEnrollment.student_id)
                .join(PlanVersion, PlanVersion.id == StudentPlanEnrollment.plan_version_id)
                .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
                .where(Rvoe.program_id == rvoe.program_id)
            )
        )
    if only_debtors:
        query = query.where(
            Student.id.in_(treasury.overdue_debtor_ids_select())  # type: ignore[attr-defined]
        )
    students = (await session.exec(query)).all()
    if not with_debt:
        return students
    debts = await treasury.students_debt_map(session, [s.id for s in students])
    out: list[StudentPublic] = []
    for student in students:
        public = StudentPublic.model_validate(student, from_attributes=True)
        public.balance, public.overdue_balance = debts.get(student.id, (0.0, 0.0))
        out.append(public)
    return out


@router.post("", status_code=201)
async def create_student(
    session: SessionDep, current_user: ServiciosEscolares, scope: CampusScope, body: StudentCreate
) -> StudentPublic:
    ensure_in_scope(scope, body.campus_id)  # can only create in a campus you belong to
    institution = await get_default_institution(session)
    student = await create_student_core(session, institution, body, current_user.email)
    await session.commit()
    await session.refresh(student)
    return student


@router.get("/{student_id}")
async def get_student(
    session: SessionDep, _: AnyStaff, scope: CampusScope, student_id: uuid.UUID
) -> StudentPublic:
    student = await session.get(Student, student_id)
    if student is None or (scope is not None and student.campus_id not in scope):
        # out-of-scope students read as not-found (don't leak other campuses)
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return student


@router.patch("/{student_id}")
async def update_student(
    session: SessionDep,
    current_user: ServiciosEscolares,
    scope: CampusScope,
    student_id: uuid.UUID,
    body: StudentUpdate,
) -> StudentPublic:
    student = await session.get(Student, student_id)
    if student is None or (scope is not None and student.campus_id not in scope):
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("campus_id") is not None:
        ensure_in_scope(scope, changes["campus_id"])  # can't move into a foreign campus
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


# --- Relatives (familiares / contactos) --------------------------------------------

@router.get("/{student_id}/relatives")
async def list_relatives(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> list[RelativePublic]:
    return (
        await session.exec(
            select(StudentRelative)
            .where(StudentRelative.student_id == student_id)
            .order_by(StudentRelative.name)
        )
    ).all()


@router.post("/{student_id}/relatives", status_code=201)
async def add_relative(
    session: SessionDep,
    current_user: ServiciosEscolares,
    student_id: uuid.UUID,
    body: RelativeIn,
) -> RelativePublic:
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    relative = StudentRelative(student_id=student_id, **body.model_dump())
    session.add(relative)
    audit.record(session, actor=current_user.email, action="student_relative.created",
                 entity="student", entity_id=str(student_id), detail=body.name)
    await session.commit()
    await session.refresh(relative)
    return relative


@router.delete("/{student_id}/relatives/{relative_id}")
async def delete_relative(
    session: SessionDep,
    current_user: ServiciosEscolares,
    student_id: uuid.UUID,
    relative_id: uuid.UUID,
) -> dict:
    relative = await session.get(StudentRelative, relative_id)
    if relative is None or relative.student_id != student_id:
        raise HTTPException(status_code=404, detail="Familiar no encontrado")
    await session.delete(relative)
    audit.record(session, actor=current_user.email, action="student_relative.deleted",
                 entity="student", entity_id=str(student_id), detail=relative.name)
    await session.commit()
    return {"ok": True}


# --- Portal access (servo parity: students see their own info) ---------------------

@router.get("/{student_id}/portal-access")
async def portal_access_status(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> dict:
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    user = (
        await session.exec(select(User).where(User.student_id == student_id))
    ).first()
    return {
        "exists": user is not None,
        "active": bool(user and user.is_active),
        "email": user.email if user else None,
    }


@router.post("/{student_id}/portal-access", status_code=201)
async def enable_portal_access(
    session: SessionDep,
    current_user: ServiciosEscolares,
    student_id: uuid.UUID,
    background: BackgroundTasks,
) -> UserPublic:
    """Create (or reactivate) the alumno account with the student's email and
    a generated password sent by email — never in this response."""
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    user, password = await grant_portal_access(session, student, current_user.email)
    await session.commit()
    await session.refresh(user)
    message = credentials_email(student.full_name, user.email, password)
    background.add_task(send_email, to=user.email, **message)
    return user


@router.delete("/{student_id}/portal-access")
async def disable_portal_access(
    session: SessionDep, current_user: ServiciosEscolares, student_id: uuid.UUID
) -> dict:
    user = (
        await session.exec(select(User).where(User.student_id == student_id))
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="El alumno no tiene acceso al portal")
    user.is_active = False
    session.add(user)
    audit.record(session, actor=current_user.email, action="portal_access.disabled",
                 entity="student", entity_id=str(student_id), detail=user.email)
    await session.commit()
    return {"ok": True}


# --- Photo (credencial-style portrait) -------------------------------------------

PHOTO_TYPES = {"image/jpeg", "image/png"}
PHOTO_MAX_BYTES = 5 * 1024 * 1024


@router.post("/{student_id}/photo")
async def upload_student_photo(
    session: SessionDep,
    current_user: ServiciosEscolares,
    student_id: uuid.UUID,
    file: UploadFile,
) -> StudentPublic:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    path = await save_upload(
        file,
        f"student-photos/{student_id}",
        allowed_types=PHOTO_TYPES,
        max_bytes=PHOTO_MAX_BYTES,
        type_error_detail="Solo se aceptan imágenes JPEG o PNG",
    )
    old_path = student.photo_path
    student.photo_path = path
    session.add(student)
    audit.record(session, actor=current_user.email, action="student.photo_uploaded",
                 entity="student", entity_id=str(student_id))
    try:
        await session.commit()
    except Exception:
        # commit failed → the DB still points at the old file; drop the new one
        await session.rollback()
        with suppress(OSError):
            Path(path).unlink(missing_ok=True)
        raise
    if old_path:
        with suppress(OSError):
            Path(old_path).unlink(missing_ok=True)  # best-effort cleanup
    await session.refresh(student)
    return student


@router.get("/{student_id}/photo")
async def get_student_photo(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> FileResponse:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if not student.photo_path or not Path(student.photo_path).is_file():
        raise HTTPException(status_code=404, detail="El alumno no tiene fotografía")
    media_type = (
        "image/png" if student.photo_path.lower().endswith(".png") else "image/jpeg"
    )
    return FileResponse(student.photo_path, media_type=media_type)


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
    session: SessionDep, current_user: ServiciosEscolares, scope: CampusScope,
    body: GroupEnrollmentCreate,
) -> GroupEnrollmentPublic:
    student = await session.get(Student, body.student_id)
    # Out-of-scope students are 404, matching get_student/update_student.
    if student is None or (scope is not None and student.campus_id not in scope):
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    ensure_in_scope(scope, group.campus_id)
    enrollment = await enroll_student_core(
        session, current_user, student, group,
        plan_subject_ids=body.plan_subject_ids,
        override_prerequisites=body.override_prerequisites,
        waive_enrollment_fee=body.waive_enrollment_fee,
    )
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.post("/group-enrollments/subjects", status_code=201)
async def add_subjects_to_group_enrollment(
    session: SessionDep, current_user: ServiciosEscolares, scope: CampusScope,
    body: GroupEnrollmentSubjectsAdd,
) -> list[SubjectEnrollmentPublic]:
    """Add plan subjects to a student already enrolled in the group (no billing)."""
    student = await session.get(Student, body.student_id)
    if student is None or (scope is not None and student.campus_id not in scope):
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    ensure_in_scope(scope, group.campus_id)
    added = await add_subjects_core(
        session, current_user, student, group,
        plan_subject_ids=body.plan_subject_ids,
        override_prerequisites=body.override_prerequisites,
    )
    await session.commit()
    for subject_enrollment in added:
        await session.refresh(subject_enrollment)
    return added


@router.post("/intake", status_code=201)
async def wizard_intake(
    session: SessionDep,
    current_user: ServiciosEscolares,
    scope: CampusScope,
    body: WizardIntakeIn,
    background: BackgroundTasks,
) -> WizardIntakeResult:
    """One submit from the inscripciones wizard: create the student (full
    capture, relatives included) and enroll them into the group — matrícula,
    plan enrollment and auto-billing reuse the existing service logic. With
    enable_portal_access the alumno account is created in the same
    transaction and the credentials are emailed after commit."""
    institution = await get_default_institution(session)
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    ensure_in_scope(scope, group.campus_id)
    student = await create_student_core(session, institution, body.student, current_user.email)
    enrollment = await enroll_student_core(
        session, current_user, student, group,
        override_prerequisites=body.override_prerequisites,
        waive_enrollment_fee=body.waive_enrollment_fee,
    )
    portal_message: tuple[str, dict] | None = None
    if body.enable_portal_access:
        user, password = await grant_portal_access(session, student, current_user.email)
        portal_message = (user.email, credentials_email(student.full_name, user.email, password))
    await session.commit()
    if portal_message:
        to, message = portal_message
        background.add_task(send_email, to=to, **message)
    await session.refresh(student)
    await session.refresh(enrollment)
    return WizardIntakeResult(
        student=StudentPublic.model_validate(student),
        enrollment=GroupEnrollmentPublic.model_validate(enrollment),
    )


def _opt(value: str | None) -> str | None:
    """Blank roster cells mean 'not provided', not an empty value."""
    if value is None:
        return None
    value = value.strip()
    return value or None


ROSTER_MAX_BYTES = 10 * 1024 * 1024


@router.post("/bulk-intake/parse")
async def parse_bulk_intake_file(
    _: ServiciosEscolares, file: UploadFile
) -> RosterParseResult:
    """Parse a roster export (servoescolar.mx .xlsx, or any .xlsx/.csv) into a
    cell grid plus the detected column→field mapping, without touching the DB.
    The UI previews it, lets staff fix the mapping, then posts the rows to
    /bulk-intake."""
    data = await file.read(ROSTER_MAX_BYTES + 1)
    if len(data) > ROSTER_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx. 10 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    return RosterParseResult(**parse_roster(data, file.filename, file.content_type))


@router.post("/bulk-intake", status_code=201)
async def bulk_intake(
    session: SessionDep, current_user: ServiciosEscolares, scope: CampusScope, body: BulkIntakeIn
) -> BulkIntakeResult:
    """Onboard a whole cohort of NEW students into one group: create + enroll +
    auto-bill each row. Existing CURPs are rejected (enroll them via the group
    flow). Each row commits on its own, so a bad row never rolls back the good
    ones; failures come back with a reason."""
    institution = await get_default_institution(session)
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    ensure_in_scope(scope, group.campus_id)
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
                    email=row.email.strip(), phone=(row.phone or "").strip(),
                    first_names=_opt(row.first_names),
                    last_name_p=_opt(row.last_name_p),
                    last_name_m=_opt(row.last_name_m),
                    sex=normalize_sex(row.sex, curp),
                    birth_date=normalize_date(row.birth_date),
                    campus_id=group.campus_id,
                )
                student = await create_student_core(
                    session, institution, student_in, current_user.email,
                    enrollment_number=_opt(row.enrollment_number),
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
        except SQLAlchemyError:
            # any other DB-level rejection (a value too long for its column…):
            # the SAVEPOINT rolled this row back, so it must not take the batch
            errors.append(BulkIntakeError(
                row=i, curp=curp, detail="La fila fue rechazada por la base de datos",
            ))
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

async def schedule_payload(session: SessionDep, student_id: uuid.UUID) -> dict:
    """Published schedule blocks of the student's active groups, read from the
    calendar system via each Group.calendar_group_id link. Shared by the staff
    route and the student portal."""
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


@router.get("/{student_id}/calendar")
async def student_calendar(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> dict:
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return await schedule_payload(session, student_id)


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
