"""Grades: teacher capture restricted to assigned groups within the open window
(RF-C01), audited changes (RT-08), actas with folio (RF-C03), kardex & progress
(RF-C05/C08) and the degree registry book (RF-C09)."""
import json
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.api.deps import AnyStaff, CurrentUser, ServiciosEscolares, SessionDep, TeacherOrAcademic
from app.api.routes.catalog import get_default_institution
from app.models import (
    ActaKind,
    DegreeRecord,
    DegreeRecordCreate,
    DegreeRecordPublic,
    EvaluationComponent,
    EvaluationKind,
    Grade,
    GradeActa,
    GradeActaPublic,
    GradeCaptureIn,
    GradePublic,
    Group,
    GroupSubject,
    Student,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    Term,
    User,
    UserRole,
)
from app.services import audit
from app.services.academics import PASSING_GRADE, curricular_progress, kardex_rows
from app.services.folios import next_folio
from app.services.treasury import has_blocking_debt

router = APIRouter(prefix="/grades", tags=["grades"])


async def _can_capture(session: SessionDep, user: User, group_subject: GroupSubject) -> None:
    """RF-C01: teachers only capture their own subjects; Servicios Escolares any."""
    if user.is_superuser or user.role in (UserRole.servicios_escolares, UserRole.admin_sistema):
        return
    if user.role == UserRole.docente and group_subject.teacher_user_id == user.id:
        return
    raise HTTPException(status_code=403, detail="No tienes asignada esta materia")


async def _capture_window_open(session: SessionDep, group_subject: GroupSubject) -> None:
    group = await session.get(Group, group_subject.group_id)
    term = await session.get(Term, group.term_id) if group else None
    if term is None or not term.grade_capture_open:
        raise HTTPException(
            status_code=409, detail="El periodo de captura de calificaciones no está abierto"
        )


@router.get("/group-subjects/{group_subject_id}/grid")
async def grade_grid(
    session: SessionDep, _: AnyStaff, group_subject_id: uuid.UUID
) -> dict:
    """Students × evaluation components matrix for capture UI."""
    group_subject = await session.get(GroupSubject, group_subject_id)
    if group_subject is None:
        raise HTTPException(status_code=404, detail="Materia de grupo no encontrada")
    components = (
        await session.exec(
            select(EvaluationComponent)
            .where(EvaluationComponent.plan_subject_id == group_subject.plan_subject_id)
            .order_by(EvaluationComponent.sequence)
        )
    ).all()
    enrollments = (
        await session.exec(
            select(SubjectEnrollment, Student)
            .join(Student, Student.id == SubjectEnrollment.student_id)
            .where(SubjectEnrollment.group_subject_id == group_subject_id)
            .order_by(Student.full_name)
        )
    ).all()
    grades = (
        await session.exec(
            select(Grade).where(
                Grade.subject_enrollment_id.in_(  # type: ignore[attr-defined]
                    [e.id for e, _ in enrollments] or [uuid.uuid4()]
                )
            )
        )
    ).all()
    grade_map = {(g.subject_enrollment_id, g.component_id): g.value for g in grades}
    return {
        "components": [c.model_dump(mode="json") for c in components],
        "rows": [
            {
                "subject_enrollment_id": str(e.id),
                "student_id": str(s.id),
                "student_name": s.full_name,
                "enrollment_number": s.enrollment_number,
                "status": e.status,
                "final_grade": e.final_grade,
                "grades": {
                    str(c.id): grade_map.get((e.id, c.id)) for c in components
                },
            }
            for e, s in enrollments
        ],
    }


async def _recompute_final(session: SessionDep, enrollment: SubjectEnrollment) -> None:
    """Weighted final from counting components once all are captured; extraordinario
    and título de suficiencia replace the final grade when present."""
    group_subject = await session.get(GroupSubject, enrollment.group_subject_id)
    components = (
        await session.exec(
            select(EvaluationComponent).where(
                EvaluationComponent.plan_subject_id == group_subject.plan_subject_id
            )
        )
    ).all()
    grades = (
        await session.exec(
            select(Grade).where(Grade.subject_enrollment_id == enrollment.id)
        )
    ).all()
    by_component = {g.component_id: g.value for g in grades}

    replacement = None
    for c in components:
        if c.kind in (EvaluationKind.extraordinario, EvaluationKind.titulo_suficiencia):
            if c.id in by_component:
                replacement = by_component[c.id]

    counting = [c for c in components if c.counts_towards_final]
    final = None
    if replacement is not None:
        final = replacement
    elif counting and all(c.id in by_component for c in counting):
        total_weight = sum(c.weight_pct for c in counting)
        if total_weight > 0:
            final = sum(by_component[c.id] * c.weight_pct for c in counting) / total_weight
    if final is not None:
        enrollment.final_grade = round(final, 1)
        enrollment.status = (
            SubjectEnrollmentStatus.aprobada
            if enrollment.final_grade >= PASSING_GRADE
            else SubjectEnrollmentStatus.reprobada
        )
        session.add(enrollment)


@router.post("/capture")
async def capture_grade(
    session: SessionDep, current_user: TeacherOrAcademic, body: GradeCaptureIn
) -> GradePublic:
    enrollment = await session.get(SubjectEnrollment, body.subject_enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Inscripción de materia no encontrada")
    group_subject = await session.get(GroupSubject, enrollment.group_subject_id)
    if group_subject is None:
        raise HTTPException(status_code=404, detail="Materia de grupo no encontrada")
    await _can_capture(session, current_user, group_subject)
    await _capture_window_open(session, group_subject)
    component = await session.get(EvaluationComponent, body.component_id)
    if component is None or component.plan_subject_id != group_subject.plan_subject_id:
        raise HTTPException(status_code=400, detail="Componente de evaluación inválido")

    existing = (
        await session.exec(
            select(Grade).where(
                Grade.subject_enrollment_id == body.subject_enrollment_id,
                Grade.component_id == body.component_id,
            )
        )
    ).first()
    if existing:
        old_value = existing.value
        existing.value = body.value
        existing.captured_by = current_user.id
        session.add(existing)
        grade = existing
        audit.record(session, actor=current_user.email, action="grade.updated",
                     entity="grade", entity_id=str(grade.id),
                     detail=f"{component.label}: {old_value} -> {body.value}")  # RT-08
    else:
        grade = Grade(
            subject_enrollment_id=body.subject_enrollment_id,
            component_id=body.component_id,
            value=body.value,
            captured_by=current_user.id,
        )
        session.add(grade)
        try:
            await session.flush()
        except IntegrityError:
            # ponytail: two concurrent captures for the same component (double
            # submit / two open tabs); ask the client to retry rather than
            # upserting mid-transaction
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="La calificación ya fue capturada, intenta de nuevo"
            )
        audit.record(session, actor=current_user.email, action="grade.captured",
                     entity="grade", entity_id=str(grade.id),
                     detail=f"{component.label}: {body.value}")
    await _recompute_final(session, enrollment)
    await session.commit()
    await session.refresh(grade)
    return grade


# --- Actas (RF-C03) ----------------------------------------------------------------

@router.post("/group-subjects/{group_subject_id}/actas", status_code=201)
async def generate_acta(
    session: SessionDep,
    current_user: ServiciosEscolares,
    group_subject_id: uuid.UUID,
    kind: ActaKind = ActaKind.ordinaria,
) -> GradeActaPublic:
    group_subject = await session.get(GroupSubject, group_subject_id)
    if group_subject is None:
        raise HTTPException(status_code=404, detail="Materia de grupo no encontrada")
    enrollments = (
        await session.exec(
            select(SubjectEnrollment, Student)
            .join(Student, Student.id == SubjectEnrollment.student_id)
            .where(SubjectEnrollment.group_subject_id == group_subject_id)
            .order_by(Student.full_name)
        )
    ).all()
    snapshot = [
        {
            "matricula": s.enrollment_number,
            "curp": s.curp,
            "nombre": s.full_name,
            "calificacion": e.final_grade,
            "estatus": e.status,
        }
        for e, s in enrollments
    ]
    institution = await get_default_institution(session)
    folio = await next_folio(session, institution.id, "acta")
    acta = GradeActa(
        group_subject_id=group_subject_id,
        kind=kind,
        folio=folio,
        snapshot=json.dumps(snapshot, ensure_ascii=False),
        generated_by=current_user.id,
    )
    session.add(acta)
    audit.record(session, actor=current_user.email, action="acta.generated",
                 entity="acta", entity_id=folio, detail=f"{kind}, {len(snapshot)} alumnos")
    await session.commit()
    await session.refresh(acta)
    return acta


@router.get("/group-subjects/{group_subject_id}/actas")
async def list_actas(
    session: SessionDep, _: AnyStaff, group_subject_id: uuid.UUID
) -> list[GradeActaPublic]:
    return (
        await session.exec(
            select(GradeActa).where(GradeActa.group_subject_id == group_subject_id)
        )
    ).all()


@router.post("/actas/{acta_id}/sign")
async def sign_acta(
    session: SessionDep, current_user: ServiciosEscolares, acta_id: uuid.UUID, signed_by_name: str
) -> GradeActaPublic:
    from app.models.common import utcnow

    acta = await session.get(GradeActa, acta_id)
    if acta is None:
        raise HTTPException(status_code=404, detail="Acta no encontrada")
    acta.signed_by_name = signed_by_name
    acta.signed_at = utcnow()
    session.add(acta)
    audit.record(session, actor=current_user.email, action="acta.signed",
                 entity="acta", entity_id=acta.folio, detail=signed_by_name)
    await session.commit()
    await session.refresh(acta)
    return acta


# --- Kardex / progress (RF-C05, RF-C08) ----------------------------------------------

@router.get("/students/{student_id}/kardex")
async def kardex(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID, plan_version_id: uuid.UUID
) -> dict:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    rows = await kardex_rows(session, student_id, plan_version_id)
    progress = await curricular_progress(session, student_id, plan_version_id)
    return {"student_id": str(student_id), "plan_version_id": str(plan_version_id),
            "rows": rows, "progress": progress}


# --- Degree registry (RF-C09) ---------------------------------------------------------

@router.get("/degree-records")
async def list_degree_records(session: SessionDep, _: AnyStaff) -> list[DegreeRecordPublic]:
    return (await session.exec(select(DegreeRecord).order_by(DegreeRecord.created_at))).all()


@router.post("/degree-records", status_code=201)
async def register_degree(
    session: SessionDep, current_user: ServiciosEscolares, body: DegreeRecordCreate
) -> DegreeRecordPublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if await has_blocking_debt(session, student):  # RF-T07
        raise HTTPException(
            status_code=409, detail="El alumno tiene adeudo vencido; trámite bloqueado (RF-T07)"
        )
    institution = await get_default_institution(session)
    folio = await next_folio(session, institution.id, body.kind.value)
    record_row = DegreeRecord(**body.model_dump(), folio=folio, registered_by=current_user.id)
    session.add(record_row)
    audit.record(session, actor=current_user.email, action="degree.registered",
                 entity="degree_record", entity_id=folio, detail=body.kind)
    await session.commit()
    await session.refresh(record_row)
    return record_row
