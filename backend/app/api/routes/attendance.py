"""Attendance: per-session roll call (RF-A01), reports & right-to-exam (RF-A05),
at-risk alerts (RF-A03) and justification flow (RF-A04)."""
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from sqlmodel import select

from app.api.deps import AnyStaff, ServiciosEscolares, SessionDep, TeacherOrAcademic
from app.models import (
    AbsenceJustification,
    AttendanceRecord,
    AttendanceRecordPublic,
    AttendanceStatus,
    ClassSession,
    ClassSessionPublic,
    GroupSubject,
    JustificationCreate,
    JustificationPublic,
    JustificationReviewIn,
    JustificationStatus,
    SessionWithAttendanceIn,
    Student,
    SubjectEnrollment,
    User,
    UserRole,
)
from app.models.common import utcnow
from app.services import audit
from app.services.academics import attendance_summary
from app.services.email import send_email
from app.services.files import save_upload

router = APIRouter(prefix="/attendance", tags=["attendance"])


async def _can_mark(user: User, group_subject: GroupSubject) -> None:
    if user.is_superuser or user.role in (
        UserRole.servicios_escolares, UserRole.admin_sistema, UserRole.coordinador_academico
    ):
        return
    if user.role == UserRole.docente and group_subject.teacher_user_id == user.id:
        return
    raise HTTPException(status_code=403, detail="No tienes asignada esta materia")


@router.post("/sessions", status_code=201)
async def record_session(
    session: SessionDep, current_user: TeacherOrAcademic, body: SessionWithAttendanceIn
) -> ClassSessionPublic:
    """RF-A01: create (or update) a session and its roll call in one request."""
    group_subject = await session.get(GroupSubject, body.group_subject_id)
    if group_subject is None:
        raise HTTPException(status_code=404, detail="Materia de grupo no encontrada")
    await _can_mark(current_user, group_subject)

    existing = (
        await session.exec(
            select(ClassSession).where(
                ClassSession.group_subject_id == body.group_subject_id,
                ClassSession.session_date == body.session_date,
                ClassSession.sequence == body.sequence,
            )
        )
    ).first()
    class_session = existing or ClassSession(
        group_subject_id=body.group_subject_id,
        session_date=body.session_date,
        sequence=body.sequence,
        notes=body.notes,
        created_by=current_user.id,
    )
    session.add(class_session)
    await session.flush()

    enrolled = set(
        (
            await session.exec(
                select(SubjectEnrollment.student_id).where(
                    SubjectEnrollment.group_subject_id == body.group_subject_id
                )
            )
        ).all()
    )
    current = {
        r.student_id: r
        for r in (
            await session.exec(
                select(AttendanceRecord).where(AttendanceRecord.session_id == class_session.id)
            )
        ).all()
    }
    for mark in body.records:
        if mark.student_id not in enrolled:
            raise HTTPException(status_code=400, detail="Alumno no inscrito en la materia")
        record = current.get(mark.student_id)
        if record:
            record.status = mark.status
            record.recorded_by = current_user.id
            session.add(record)
        else:
            session.add(
                AttendanceRecord(
                    session_id=class_session.id,
                    student_id=mark.student_id,
                    status=mark.status,
                    recorded_by=current_user.id,
                )
            )
    audit.record(session, actor=current_user.email, action="attendance.recorded",
                 entity="class_session", entity_id=str(class_session.id),
                 detail=f"{body.session_date} ({len(body.records)} alumnos)")
    await session.commit()
    await session.refresh(class_session)
    return class_session


@router.get("/group-subjects/{group_subject_id}/sessions")
async def list_sessions(
    session: SessionDep, _: AnyStaff, group_subject_id: uuid.UUID
) -> list[ClassSessionPublic]:
    return (
        await session.exec(
            select(ClassSession)
            .where(ClassSession.group_subject_id == group_subject_id)
            .order_by(ClassSession.session_date, ClassSession.sequence)
        )
    ).all()


@router.get("/sessions/{session_id}/records")
async def session_records(
    session: SessionDep, _: AnyStaff, session_id: uuid.UUID
) -> list[AttendanceRecordPublic]:
    return (
        await session.exec(
            select(AttendanceRecord).where(AttendanceRecord.session_id == session_id)
        )
    ).all()


@router.get("/group-subjects/{group_subject_id}/report")
async def attendance_report(
    session: SessionDep, _: AnyStaff, group_subject_id: uuid.UUID
) -> list[dict]:
    """RF-A05: per-student attendance % and right-to-exam for a subject."""
    student_ids = (
        await session.exec(
            select(SubjectEnrollment.student_id).where(
                SubjectEnrollment.group_subject_id == group_subject_id
            )
        )
    ).all()
    students = {
        s.id: s
        for s in (
            await session.exec(select(Student).where(Student.id.in_(student_ids)))
        ).all()
    }
    out = []
    for student_id in student_ids:
        summary = await attendance_summary(session, student_id, group_subject_id)
        student = students.get(student_id)
        summary["student_name"] = student.full_name if student else ""
        summary["enrollment_number"] = student.enrollment_number if student else ""
        out.append(summary)
    return out


@router.post("/group-subjects/{group_subject_id}/notify-at-risk")
async def notify_at_risk(
    session: SessionDep,
    current_user: ServiciosEscolares,
    group_subject_id: uuid.UUID,
    background: BackgroundTasks,
    threshold_margin: float = 5.0,
) -> dict:
    """RF-A03: email students at or near the absence limit (and log the alert)."""
    report = await attendance_report(session, current_user, group_subject_id)
    notified = 0
    for row in report:
        at_risk = row["attendance_pct"] < row["min_attendance_pct"] + threshold_margin
        if not at_risk or not row["sessions"]:
            continue
        student = await session.get(Student, uuid.UUID(row["student_id"]))
        if student and student.email:
            background.add_task(
                send_email,
                to=student.email,
                subject="Alerta de asistencia — INUE",
                html=(
                    f"<p>Hola {student.full_name},</p><p>Tu asistencia es de "
                    f"{row['attendance_pct']}% y el mínimo para derecho a examen es "
                    f"{row['min_attendance_pct']}%. Acude a Coordinación Académica.</p>"
                ),
            )
        notified += 1
    audit.record(session, actor=current_user.email, action="attendance.risk_alerts_sent",
                 entity="group_subject", entity_id=str(group_subject_id), detail=str(notified))
    await session.commit()
    return {"notified": notified}


# --- Justifications (RF-A04) -----------------------------------------------------

@router.post("/justifications", status_code=201)
async def create_justification(
    session: SessionDep, current_user: AnyStaff, body: JustificationCreate
) -> JustificationPublic:
    if await session.get(Student, body.student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if body.date_to < body.date_from:
        raise HTTPException(status_code=400, detail="Rango de fechas inválido")
    justification = AbsenceJustification(**body.model_dump())
    session.add(justification)
    audit.record(session, actor=current_user.email, action="justification.created",
                 entity="justification", entity_id=str(justification.id))
    await session.commit()
    await session.refresh(justification)
    return justification


@router.post("/justifications/{justification_id}/evidence")
async def upload_evidence(
    session: SessionDep, current_user: AnyStaff, justification_id: uuid.UUID, file: UploadFile
) -> JustificationPublic:
    justification = await session.get(AbsenceJustification, justification_id)
    if justification is None:
        raise HTTPException(status_code=404, detail="Justificante no encontrado")
    path = await save_upload(file, "justifications")
    justification.evidence_path = path
    justification.evidence_filename = file.filename or "evidencia"
    session.add(justification)
    audit.record(session, actor=current_user.email, action="justification.evidence_uploaded",
                 entity="justification", entity_id=str(justification_id))
    await session.commit()
    await session.refresh(justification)
    return justification


@router.get("/justifications")
async def list_justifications(
    session: SessionDep,
    _: AnyStaff,
    student_id: uuid.UUID | None = None,
    status: JustificationStatus | None = None,
) -> list[JustificationPublic]:
    q = select(AbsenceJustification).order_by(AbsenceJustification.created_at.desc())
    if student_id:
        q = q.where(AbsenceJustification.student_id == student_id)
    if status:
        q = q.where(AbsenceJustification.status == status)
    return (await session.exec(q)).all()


@router.post("/justifications/{justification_id}/review")
async def review_justification(
    session: SessionDep,
    current_user: ServiciosEscolares,
    justification_id: uuid.UUID,
    body: JustificationReviewIn,
) -> JustificationPublic:
    """On approval, flip matching 'falta' records to 'justificado' (RF-A04)."""
    justification = await session.get(AbsenceJustification, justification_id)
    if justification is None:
        raise HTTPException(status_code=404, detail="Justificante no encontrado")
    justification.status = body.status
    justification.review_notes = body.review_notes
    justification.reviewed_by = current_user.id
    justification.reviewed_at = utcnow()
    session.add(justification)

    flipped = 0
    if body.status == JustificationStatus.aprobado:
        records = (
            await session.exec(
                select(AttendanceRecord)
                .join(ClassSession, ClassSession.id == AttendanceRecord.session_id)
                .where(
                    AttendanceRecord.student_id == justification.student_id,
                    AttendanceRecord.status == AttendanceStatus.falta,
                    ClassSession.session_date >= justification.date_from,
                    ClassSession.session_date <= justification.date_to,
                )
            )
        ).all()
        for record in records:
            record.status = AttendanceStatus.justificado
            session.add(record)
            flipped += 1
    audit.record(session, actor=current_user.email, action="justification.reviewed",
                 entity="justification", entity_id=str(justification_id),
                 detail=f"{body.status} ({flipped} faltas justificadas)")
    await session.commit()
    await session.refresh(justification)
    return justification
