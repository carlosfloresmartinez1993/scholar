"""Student record / documentation module: digital expediente (RF-D01), intake
checklist (RF-D02), uploaded document review (RF-D03), official issued documents
with auditable folios (RF-D04/D05), school regulations acceptance (RF-D06) and
teacher expedientes (RF-D07)."""
import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.common import utcnow
from app.models.catalog import EducationLevel
from app.models.student import AdmissionType


class RequirementBase(SQLModel):
    name: str = Field(max_length=255)  # e.g. "Acta de nacimiento"
    level: EducationLevel | None = None  # None = all levels
    admission_type: AdmissionType | None = None  # None = all admission types
    required: bool = True


class DocumentRequirement(RequirementBase, table=True):
    """RF-D02: configurable intake checklist per level / admission type."""
    __tablename__ = "document_requirements"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    is_active: bool = True


class RequirementCreate(RequirementBase):
    pass


class RequirementPublic(RequirementBase):
    id: uuid.UUID
    is_active: bool


class ReviewStatus(str, Enum):
    pendiente = "pendiente"
    aceptado = "aceptado"
    rechazado = "rechazado"


class StudentDocument(SQLModel, table=True):
    """RF-D03: uploaded file with version control and review status."""
    __tablename__ = "student_documents"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    requirement_id: uuid.UUID | None = Field(
        default=None, foreign_key="document_requirements.id", index=True
    )
    title: str = Field(max_length=255)
    file_path: str = Field(max_length=512)
    filename: str = Field(max_length=255)
    content_type: str = Field(default="application/pdf", max_length=128)
    version: int = Field(default=1, ge=1)
    status: ReviewStatus = ReviewStatus.pendiente
    reject_reason: str = Field(default="", max_length=512)
    reviewed_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = None
    uploaded_by: uuid.UUID = Field(foreign_key="users.id")
    uploaded_at: datetime = Field(default_factory=utcnow)


class StudentDocumentPublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    requirement_id: uuid.UUID | None
    title: str
    filename: str
    content_type: str
    version: int
    status: ReviewStatus
    reject_reason: str
    uploaded_at: datetime


class DocumentReviewIn(SQLModel):
    status: ReviewStatus
    reject_reason: str = ""


class IssuedDocumentKind(str, Enum):
    constancia_estudios = "constancia_estudios"
    constancia_no_adeudo = "constancia_no_adeudo"
    carta_pasante = "carta_pasante"
    kardex = "kardex"
    certificado_parcial = "certificado_parcial"
    certificado_total = "certificado_total"


class IssuedDocument(SQLModel, table=True):
    """RF-D04/D05: official documents with unique sequential folio; the payload
    is a frozen JSON snapshot (student, RVOE, plan, grades…) for reprinting."""
    __tablename__ = "issued_documents"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    kind: IssuedDocumentKind
    folio: str = Field(unique=True, max_length=32)
    payload: str  # JSON snapshot at issue time
    issued_by: uuid.UUID = Field(foreign_key="users.id")
    issued_at: datetime = Field(default_factory=utcnow)


class IssuedDocumentPublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    kind: IssuedDocumentKind
    folio: str
    payload: str
    issued_at: datetime


class IssueDocumentIn(SQLModel):
    student_id: uuid.UUID
    kind: IssuedDocumentKind
    plan_version_id: uuid.UUID | None = None  # required for kardex/certificados
    notes: str = ""


class Regulation(SQLModel, table=True):
    """RF-D06: published school regulation; students accept digitally."""
    __tablename__ = "regulations"
    __table_args__ = (UniqueConstraint("institution_id", "version", name="uq_regulation_version"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    version: str = Field(max_length=32)
    title: str = Field(max_length=255)
    content_url: str = Field(default="", max_length=512)
    body: str = Field(default="")  # inline text alternative
    is_current: bool = True
    published_at: datetime = Field(default_factory=utcnow)


class RegulationCreate(SQLModel):
    version: str
    title: str
    content_url: str = ""
    body: str = ""


class RegulationPublic(SQLModel):
    id: uuid.UUID
    version: str
    title: str
    content_url: str
    body: str
    is_current: bool
    published_at: datetime


class RegulationAcceptance(SQLModel, table=True):
    __tablename__ = "regulation_acceptances"
    __table_args__ = (UniqueConstraint("regulation_id", "student_id", name="uq_reg_acceptance"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    regulation_id: uuid.UUID = Field(foreign_key="regulations.id", index=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    accepted_at: datetime = Field(default_factory=utcnow)
    recorded_by: uuid.UUID = Field(foreign_key="users.id")


class TeacherProfileBase(SQLModel):
    cedula_profesional: str = Field(default="", max_length=32)
    max_degree: str = Field(default="", max_length=128)  # e.g. "Maestría en Derecho Fiscal"
    cv_summary: str = Field(default="", max_length=2048)


class TeacherProfile(TeacherProfileBase, table=True):
    """RF-D07: expediente docente tied to a user with role docente."""
    __tablename__ = "teacher_profiles"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class TeacherProfileUpsert(TeacherProfileBase):
    user_id: uuid.UUID


class TeacherProfilePublic(TeacherProfileBase):
    id: uuid.UUID
    user_id: uuid.UUID


class TeacherDocument(SQLModel, table=True):
    """Documentación probatoria del docente (cédula, grados, CV)."""
    __tablename__ = "teacher_documents"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    teacher_profile_id: uuid.UUID = Field(foreign_key="teacher_profiles.id", index=True)
    title: str = Field(max_length=255)
    file_path: str = Field(max_length=512)
    filename: str = Field(max_length=255)
    content_type: str = Field(default="application/pdf", max_length=128)
    uploaded_by: uuid.UUID = Field(foreign_key="users.id")
    uploaded_at: datetime = Field(default_factory=utcnow)


class TeacherDocumentPublic(SQLModel):
    id: uuid.UUID
    teacher_profile_id: uuid.UUID
    title: str
    filename: str
    uploaded_at: datetime
