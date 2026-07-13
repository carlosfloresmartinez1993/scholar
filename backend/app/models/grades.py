"""Grades module: configurable evaluation schemes (RF-C02), grade capture (RF-C01),
actas (RF-C03) and the degree registry book (RF-C09)."""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.common import utcnow


class EvaluationKind(str, Enum):
    parcial = "parcial"
    ordinario = "ordinario"
    extraordinario = "extraordinario"
    titulo_suficiencia = "titulo_suficiencia"


class EvaluationComponentBase(SQLModel):
    kind: EvaluationKind
    label: str = Field(max_length=64)  # e.g. "Parcial 1"
    weight_pct: float = Field(ge=0, le=100)  # weight within the final grade
    sequence: int = Field(default=1, ge=1)
    counts_towards_final: bool = True  # extraordinario/título replace, not weigh


class EvaluationComponent(EvaluationComponentBase, table=True):
    """Evaluation scheme per plan subject (RF-C02) — same-named subjects in
    different programs/RVOE may grade differently."""
    __tablename__ = "evaluation_components"
    __table_args__ = (
        UniqueConstraint("plan_subject_id", "label", name="uq_eval_component_label"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    plan_subject_id: uuid.UUID = Field(foreign_key="plan_subjects.id", index=True)


class EvaluationComponentCreate(EvaluationComponentBase):
    plan_subject_id: uuid.UUID


class EvaluationComponentPublic(EvaluationComponentBase):
    id: uuid.UUID
    plan_subject_id: uuid.UUID


class Grade(SQLModel, table=True):
    """One captured grade for one evaluation component of a subject enrollment.
    Every change is audited with previous value (RT-08)."""
    __tablename__ = "grades"
    __table_args__ = (
        UniqueConstraint("subject_enrollment_id", "component_id", name="uq_grade_component"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    subject_enrollment_id: uuid.UUID = Field(foreign_key="subject_enrollments.id", index=True)
    component_id: uuid.UUID = Field(foreign_key="evaluation_components.id", index=True)
    value: float = Field(ge=0, le=10)
    captured_by: uuid.UUID = Field(foreign_key="users.id")
    captured_at: datetime = Field(default_factory=utcnow)


class GradeCaptureIn(SQLModel):
    subject_enrollment_id: uuid.UUID
    component_id: uuid.UUID
    value: float = Field(ge=0, le=10)


class GradePublic(SQLModel):
    id: uuid.UUID
    subject_enrollment_id: uuid.UUID
    component_id: uuid.UUID
    value: float
    captured_at: datetime


class ActaKind(str, Enum):
    ordinaria = "ordinaria"
    extraordinaria = "extraordinaria"


class GradeActa(SQLModel, table=True):
    """Acta de calificaciones per group-subject (RF-C03). Content is a frozen
    JSON snapshot of the grades at generation time; folio is unique (RF-D05)."""
    __tablename__ = "grade_actas"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_subject_id: uuid.UUID = Field(foreign_key="group_subjects.id", index=True)
    kind: ActaKind
    folio: str = Field(unique=True, max_length=32)
    snapshot: str  # JSON: rows of {student, matricula, grade}
    generated_by: uuid.UUID = Field(foreign_key="users.id")
    generated_at: datetime = Field(default_factory=utcnow)
    signed_by_name: str = Field(default="", max_length=255)
    signed_at: datetime | None = None


class GradeActaPublic(SQLModel):
    id: uuid.UUID
    group_subject_id: uuid.UUID
    kind: ActaKind
    folio: str
    snapshot: str
    generated_at: datetime
    signed_by_name: str
    signed_at: datetime | None


class DegreeKind(str, Enum):
    titulo = "titulo"
    diploma = "diploma"
    grado = "grado"


class DegreeRecordBase(SQLModel):
    kind: DegreeKind
    program_name: str = Field(max_length=255)
    issue_date: date
    notes: str = Field(default="", max_length=512)


class DegreeRecord(DegreeRecordBase, table=True):
    """Libro de registro de títulos, diplomas y grados (RF-C09)."""
    __tablename__ = "degree_records"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    folio: str = Field(unique=True, max_length=32)
    registered_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class DegreeRecordCreate(DegreeRecordBase):
    student_id: uuid.UUID


class DegreeRecordPublic(DegreeRecordBase):
    id: uuid.UUID
    student_id: uuid.UUID
    folio: str
    created_at: datetime
