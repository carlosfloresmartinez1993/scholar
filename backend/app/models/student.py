"""Students, program enrollment (per plan version / RVOE) and group enrollment.

CURP is the unique institutional identifier (RT-09).
"""
import re
import uuid
from datetime import datetime
from enum import Enum

from pydantic import field_validator
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.common import utcnow

CURP_RE = re.compile(r"^[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[0-9A-Z]\d$")


class StudentStatus(str, Enum):
    activo = "activo"
    baja_temporal = "baja_temporal"
    baja_definitiva = "baja_definitiva"
    egresado = "egresado"


class AdmissionType(str, Enum):
    nuevo_ingreso = "nuevo_ingreso"
    revalidacion = "revalidacion"
    equivalencia = "equivalencia"
    movilidad = "movilidad"


class StudentBase(SQLModel):
    curp: str = Field(max_length=18, index=True)
    full_name: str = Field(max_length=255)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=32)
    status: StudentStatus = StudentStatus.activo
    admission_type: AdmissionType = AdmissionType.nuevo_ingreso

    @field_validator("curp")
    @classmethod
    def _valid_curp(cls, v: str) -> str:
        v = v.strip().upper()
        if not CURP_RE.match(v):
            raise ValueError("CURP inválida")
        return v


class Student(StudentBase, table=True):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("institution_id", "curp", name="uq_student_curp"),
        UniqueConstraint("institution_id", "enrollment_number", name="uq_student_matricula"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    campus_id: uuid.UUID = Field(foreign_key="campuses.id", index=True)
    enrollment_number: str = Field(max_length=32)  # matrícula, assigned on create
    created_at: datetime = Field(default_factory=utcnow)


class StudentCreate(StudentBase):
    campus_id: uuid.UUID


class StudentUpdate(SQLModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: StudentStatus | None = None
    campus_id: uuid.UUID | None = None


class StudentPublic(StudentBase):
    id: uuid.UUID
    institution_id: uuid.UUID
    campus_id: uuid.UUID
    enrollment_number: str
    created_at: datetime


# --- Bulk cohort intake: create + enroll many new students into one group -------

class BulkIntakeRow(SQLModel):
    # plain str (validated when built into a StudentCreate, so bad rows are reported
    # instead of failing the whole request)
    curp: str
    full_name: str
    email: str = ""


class BulkIntakeIn(SQLModel):
    group_id: uuid.UUID
    # non-empty, capped: each row runs queries + billing writes in one request
    rows: list[BulkIntakeRow] = Field(min_length=1, max_length=1000)
    override_prerequisites: bool = False
    waive_enrollment_fee: bool = False


class BulkIntakeError(SQLModel):
    row: int  # 1-based row number in the submitted roster
    curp: str
    detail: str


class BulkIntakeResult(SQLModel):
    enrolled: int
    errors: list[BulkIntakeError]


class PlanEnrollmentStatus(str, Enum):
    inscrito = "inscrito"
    baja = "baja"
    egresado = "egresado"
    titulado = "titulado"


class StudentPlanEnrollment(SQLModel, table=True):
    """Enrollment of a student into a plan version — fixes the RVOE that governs
    their whole academic record (RF-C04). A student may hold more than one
    (e.g. licenciatura + maestría)."""
    __tablename__ = "student_plan_enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "plan_version_id", name="uq_student_plan"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    plan_version_id: uuid.UUID = Field(foreign_key="plan_versions.id", index=True)
    start_term_id: uuid.UUID = Field(foreign_key="terms.id")
    status: PlanEnrollmentStatus = PlanEnrollmentStatus.inscrito
    created_at: datetime = Field(default_factory=utcnow)


class PlanEnrollmentCreate(SQLModel):
    student_id: uuid.UUID
    plan_version_id: uuid.UUID
    start_term_id: uuid.UUID


class PlanEnrollmentPublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    plan_version_id: uuid.UUID
    start_term_id: uuid.UUID
    status: PlanEnrollmentStatus
    created_at: datetime


class GroupEnrollmentKind(str, Enum):
    inscripcion = "inscripcion"
    reinscripcion = "reinscripcion"


class GroupEnrollmentStatus(str, Enum):
    activa = "activa"
    baja = "baja"


class GroupEnrollment(SQLModel, table=True):
    """Student in a group for a term (RT-10 uses kind to split inscritos/reinscritos)."""
    __tablename__ = "group_enrollments"
    __table_args__ = (UniqueConstraint("student_id", "group_id", name="uq_group_enrollment"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    group_id: uuid.UUID = Field(foreign_key="groups.id", index=True)
    plan_enrollment_id: uuid.UUID = Field(foreign_key="student_plan_enrollments.id", index=True)
    kind: GroupEnrollmentKind = GroupEnrollmentKind.inscripcion
    status: GroupEnrollmentStatus = GroupEnrollmentStatus.activa
    created_at: datetime = Field(default_factory=utcnow)


class GroupEnrollmentCreate(SQLModel):
    student_id: uuid.UUID
    group_id: uuid.UUID
    # kind (inscripción/reinscripción) is derived server-side from enrollment history
    # subjects to enroll; empty = all subjects of the group
    plan_subject_ids: list[uuid.UUID] = []
    # skip seriación validation (requires servicios_escolares role; audited)
    override_prerequisites: bool = False
    # some new students don't pay inscripción — skip the enrollment-fee charge
    waive_enrollment_fee: bool = False


class GroupEnrollmentPublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    group_id: uuid.UUID
    plan_enrollment_id: uuid.UUID
    kind: GroupEnrollmentKind
    status: GroupEnrollmentStatus
    created_at: datetime


class SubjectEnrollmentStatus(str, Enum):
    cursando = "cursando"
    aprobada = "aprobada"
    reprobada = "reprobada"
    baja = "baja"


class SubjectEnrollment(SQLModel, table=True):
    """A student taking one subject in a group; final grade lives here once closed."""
    __tablename__ = "subject_enrollments"
    __table_args__ = (
        UniqueConstraint("group_enrollment_id", "group_subject_id", name="uq_subject_enrollment"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_enrollment_id: uuid.UUID = Field(foreign_key="group_enrollments.id", index=True)
    group_subject_id: uuid.UUID = Field(foreign_key="group_subjects.id", index=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    attempt_number: int = Field(default=1, ge=1)
    status: SubjectEnrollmentStatus = SubjectEnrollmentStatus.cursando
    final_grade: float | None = Field(default=None, ge=0, le=10)
    created_at: datetime = Field(default_factory=utcnow)


class SubjectEnrollmentPublic(SQLModel):
    id: uuid.UUID
    group_enrollment_id: uuid.UUID
    group_subject_id: uuid.UUID
    student_id: uuid.UUID
    attempt_number: int
    status: SubjectEnrollmentStatus
    final_grade: float | None
