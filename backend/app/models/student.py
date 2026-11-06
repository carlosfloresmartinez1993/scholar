"""Students, program enrollment (per plan version / RVOE) and group enrollment.

CURP is the unique institutional identifier (RT-09).
"""
import re
import uuid
from datetime import date, datetime
from enum import Enum

from pydantic import field_validator, model_validator
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


class Sex(str, Enum):
    F = "F"
    M = "M"


class StudentBase(SQLModel):
    curp: str = Field(max_length=18, index=True)
    full_name: str = Field(max_length=255)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=32)  # móvil
    status: StudentStatus = StudentStatus.activo
    admission_type: AdmissionType = AdmissionType.nuevo_ingreso
    # --- wizard capture (all optional; full_name stays the source of truth) ---
    last_name_p: str | None = Field(default=None, max_length=100)
    last_name_m: str | None = Field(default=None, max_length=100)
    first_names: str | None = Field(default=None, max_length=100)
    sex: Sex | None = None
    birth_date: date | None = None
    birth_country: str | None = Field(default=None, max_length=64)
    birth_state: str | None = Field(default=None, max_length=64)
    birth_place: str | None = Field(default=None, max_length=128)
    # Domicilio — free-text capture (ponytail: no SEPOMEX catalog; staff types it)
    street: str | None = Field(default=None, max_length=128)
    ext_no: str | None = Field(default=None, max_length=16)
    int_no: str | None = Field(default=None, max_length=16)
    address_reference: str | None = Field(default=None, max_length=255)
    colonia: str | None = Field(default=None, max_length=128)
    municipio: str | None = Field(default=None, max_length=128)
    locality: str | None = Field(default=None, max_length=128)
    address_state: str | None = Field(default=None, max_length=64)
    address_country: str | None = Field(default=None, max_length=64)
    postal_code: str | None = Field(default=None, max_length=5)
    # Contacto extra
    phone_home: str | None = Field(default=None, max_length=32)
    phone_work: str | None = Field(default=None, max_length=32)
    # Historial académico
    previous_school: str | None = Field(default=None, max_length=255)
    previous_gpa: float | None = Field(default=None, ge=0, le=10)
    enrollment_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("curp")
    @classmethod
    def _valid_curp(cls, v: str) -> str:
        v = v.strip().upper()
        if not CURP_RE.match(v):
            raise ValueError("CURP inválida")
        return v

    @field_validator("postal_code")
    @classmethod
    def _valid_postal_code(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError("Código postal inválido (5 dígitos)")
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
    photo_path: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def has_photo(self) -> bool:
        return self.photo_path is not None


class StudentRelative(SQLModel, table=True):
    """Familiar / contacto del alumno (madre, padre, tutor…)."""
    __tablename__ = "student_relatives"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    name: str = Field(max_length=255)
    relationship: str = Field(max_length=32)  # madre/padre/tutor/cónyuge/hermano(a)/otro
    phone: str | None = Field(default=None, max_length=32)


class RelativeIn(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    relationship: str = Field(min_length=1, max_length=32)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("name", "relationship")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("no puede estar vacío")
        return value


class RelativePublic(RelativeIn):
    id: uuid.UUID
    student_id: uuid.UUID


class StudentCreate(StudentBase):
    campus_id: uuid.UUID
    # optional when the split name is provided (the wizard sends the parts)
    full_name: str = Field(default="", max_length=255)
    # nested capture from the wizard; also editable later via /students/{id}/relatives
    relatives: list[RelativeIn] = []

    @model_validator(mode="after")
    def _compose_full_name(self) -> "StudentCreate":
        if not self.full_name.strip():
            parts = [self.first_names, self.last_name_p, self.last_name_m]
            composed = " ".join(p.strip() for p in parts if p and p.strip())
            if not composed:
                raise ValueError("Se requiere el nombre completo o nombre(s) y apellidos")
            self.full_name = composed
        return self


class StudentUpdate(SQLModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: StudentStatus | None = None
    campus_id: uuid.UUID | None = None
    last_name_p: str | None = None
    last_name_m: str | None = None
    first_names: str | None = None
    sex: Sex | None = None
    birth_date: date | None = None
    birth_country: str | None = None
    birth_state: str | None = None
    birth_place: str | None = None
    street: str | None = None
    ext_no: str | None = None
    int_no: str | None = None
    address_reference: str | None = None
    colonia: str | None = None
    municipio: str | None = None
    locality: str | None = None
    address_state: str | None = None
    address_country: str | None = None
    postal_code: str | None = None
    phone_home: str | None = None
    phone_work: str | None = None
    previous_school: str | None = None
    previous_gpa: float | None = Field(default=None, ge=0, le=10)
    enrollment_notes: str | None = None

    @field_validator("postal_code")
    @classmethod
    def _valid_postal_code(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError("Código postal inválido (5 dígitos)")
        return v


class StudentPublic(StudentBase):
    id: uuid.UUID
    institution_id: uuid.UUID
    campus_id: uuid.UUID
    enrollment_number: str
    created_at: datetime
    # the file itself is served by GET /students/{id}/photo (path never leaks)
    has_photo: bool = False
    # Adeudo, filled only when the caller asks for it (?with_debt=true) — computing
    # it costs two extra grouped queries. None means "not computed", which the UI
    # must not draw as $0.00: a student with no charges really does owe nothing.
    balance: float | None = None
    overdue_balance: float | None = None


# --- Bulk cohort intake: create + enroll many new students into one group -------

class BulkIntakeRow(SQLModel):
    # plain str (validated when built into a StudentCreate, so bad rows are reported
    # instead of failing the whole request)
    curp: str
    # full_name may be empty when the split name is given (Servo exports carry
    # Apellido paterno / Apellido materno / Nombre(s) as separate columns)
    full_name: str = ""
    email: str = ""
    # --- optional columns of a servoescolar.mx export ---
    # existing matrícula to keep instead of assigning a new one (migration).
    # Length is checked while creating the student, so an over-long cell (a
    # column mis-mapped to Matrícula) is reported as one bad row, not a 422 for
    # the whole batch.
    enrollment_number: str | None = None
    first_names: str | None = None
    last_name_p: str | None = None
    last_name_m: str | None = None
    phone: str | None = None
    sex: str | None = None  # F/M or Femenino/Masculino… normalized on intake
    birth_date: str | None = None  # ISO or dd/mm/yyyy, normalized on intake


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


class RosterParseResult(SQLModel):
    """A parsed roster file: the raw cell grid plus which column feeds each
    intake field (None = not detected; the UI lets staff pick one)."""
    columns: list[str]
    mapping: dict[str, int | None]
    rows: list[list[str]]
    header_row: int | None  # None = no header recognized, positional layout assumed
    truncated: bool  # more rows than the bulk-intake cap; only the first cap kept
    skipped: int  # rows dropped as noise (blank in every identified name/CURP column)


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


class GroupEnrollmentSubjectsAdd(SQLModel):
    """Add plan subjects to a student already enrolled in the group."""
    student_id: uuid.UUID
    group_id: uuid.UUID
    plan_subject_ids: list[uuid.UUID]
    override_prerequisites: bool = False


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

# --- Wizard intake: create + enroll ONE student in a single submit ----------------

class WizardIntakeIn(SQLModel):
    student: StudentCreate
    group_id: uuid.UUID
    waive_enrollment_fee: bool = False
    override_prerequisites: bool = False
    # step 6 of the wizard: create the portal account + email credentials
    enable_portal_access: bool = False


class WizardIntakeResult(SQLModel):
    student: StudentPublic
    enrollment: GroupEnrollmentPublic
