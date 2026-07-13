"""Attendance module: sessions and per-student records (RF-A01), justifications
with approval flow (RF-A04). Minimum-attendance thresholds live on PlanVersion
(RF-A02); participation evidence for non-schooled modalities uses the
`participacion` status (RF-A06)."""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.common import utcnow


class AttendanceStatus(str, Enum):
    presente = "presente"
    falta = "falta"
    retardo = "retardo"
    justificado = "justificado"
    participacion = "participacion"  # evidencia de participación (modalidad mixta/distancia)


class ClassSession(SQLModel, table=True):
    """One held session of a group-subject on a date (RF-A01)."""
    __tablename__ = "class_sessions"
    __table_args__ = (
        UniqueConstraint("group_subject_id", "session_date", "sequence", name="uq_session"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_subject_id: uuid.UUID = Field(foreign_key="group_subjects.id", index=True)
    session_date: date = Field(index=True)
    sequence: int = Field(default=1, ge=1)  # allows two sessions same day
    notes: str = Field(default="", max_length=512)
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class ClassSessionPublic(SQLModel):
    id: uuid.UUID
    group_subject_id: uuid.UUID
    session_date: date
    sequence: int
    notes: str


class AttendanceRecord(SQLModel, table=True):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_attendance"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="class_sessions.id", index=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    status: AttendanceStatus
    recorded_by: uuid.UUID = Field(foreign_key="users.id")
    recorded_at: datetime = Field(default_factory=utcnow)


class AttendanceMarkIn(SQLModel):
    student_id: uuid.UUID
    status: AttendanceStatus


class SessionWithAttendanceIn(SQLModel):
    group_subject_id: uuid.UUID
    session_date: date
    sequence: int = 1
    notes: str = ""
    records: list[AttendanceMarkIn] = []


class AttendanceRecordPublic(SQLModel):
    id: uuid.UUID
    session_id: uuid.UUID
    student_id: uuid.UUID
    status: AttendanceStatus


class JustificationStatus(str, Enum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"


class JustificationBase(SQLModel):
    reason: str = Field(max_length=512)
    date_from: date
    date_to: date


class AbsenceJustification(JustificationBase, table=True):
    """RF-A04: on approval, matching 'falta' records flip to 'justificado'."""
    __tablename__ = "absence_justifications"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    evidence_path: str = Field(default="", max_length=512)
    evidence_filename: str = Field(default="", max_length=255)
    status: JustificationStatus = JustificationStatus.pendiente
    review_notes: str = Field(default="", max_length=512)
    reviewed_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class JustificationCreate(JustificationBase):
    student_id: uuid.UUID


class JustificationReviewIn(SQLModel):
    status: JustificationStatus
    review_notes: str = ""


class JustificationPublic(JustificationBase):
    id: uuid.UUID
    student_id: uuid.UUID
    evidence_filename: str
    status: JustificationStatus
    review_notes: str
    created_at: datetime
