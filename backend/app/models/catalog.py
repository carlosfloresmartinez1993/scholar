"""Academic catalog: institution, campus, programs, RVOE, plan versions, subjects, terms, groups.

RVOE is the master entity (RT-01/RT-02): one per Program + Modality + Campus.
Plan versions hang off an RVOE (RT-04) so old generations keep their curriculum.
"""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.common import utcnow


class Modality(str, Enum):
    escolarizada = "escolarizada"
    no_escolarizada = "no_escolarizada"
    mixta = "mixta"


class EducationLevel(str, Enum):
    tsu = "tsu"
    licenciatura = "licenciatura"
    especialidad = "especialidad"
    maestria = "maestria"
    doctorado = "doctorado"


class RvoeAuthority(str, Enum):
    federal = "federal"
    estatal = "estatal"


class RvoeStatus(str, Enum):
    vigente = "vigente"
    en_tramite_modificacion = "en_tramite_modificacion"
    cancelado = "cancelado"
    no_autorizado = "no_autorizado"


class PeriodType(str, Enum):
    semestral = "semestral"
    cuatrimestral = "cuatrimestral"
    anual = "anual"


# --- Institution / Campus (RT-05, RNF-02: multi-tenant ready) ---------------

class InstitutionBase(SQLModel):
    name: str = Field(max_length=255)
    short_name: str = Field(max_length=64)
    # Treasury config (RF-T06/T07)
    late_fee_pct: float = Field(default=0.0, ge=0)
    late_fee_grace_days: int = Field(default=0, ge=0)
    block_documents_on_debt: bool = True


class Institution(InstitutionBase, table=True):
    __tablename__ = "institutions"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)


class InstitutionPublic(InstitutionBase):
    id: uuid.UUID


class InstitutionUpdate(SQLModel):
    name: str | None = None
    short_name: str | None = None
    late_fee_pct: float | None = None
    late_fee_grace_days: int | None = None
    block_documents_on_debt: bool | None = None


class CampusBase(SQLModel):
    name: str = Field(max_length=255)
    address: str = Field(default="", max_length=512)
    is_active: bool = True


class Campus(CampusBase, table=True):
    __tablename__ = "campuses"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class CampusCreate(CampusBase):
    institution_id: uuid.UUID | None = None  # defaults to the single institution


class CampusPublic(CampusBase):
    id: uuid.UUID
    institution_id: uuid.UUID


# --- Program / RVOE (RT-01, RT-02, RT-03) ------------------------------------

class ProgramBase(SQLModel):
    code: str = Field(max_length=32)
    name: str = Field(max_length=255)
    level: EducationLevel


class Program(ProgramBase, table=True):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("institution_id", "code", name="uq_program_code"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class ProgramCreate(ProgramBase):
    pass


class ProgramPublic(ProgramBase):
    id: uuid.UUID
    institution_id: uuid.UUID
    is_active: bool


class RvoeBase(SQLModel):
    agreement_number: str = Field(max_length=64)  # número de acuerdo/oficio
    authority: RvoeAuthority
    modality: Modality
    issue_date: date
    valid_until: date | None = None  # vigencia, si aplica
    status: RvoeStatus = RvoeStatus.vigente
    notes: str = Field(default="", max_length=1024)


class Rvoe(RvoeBase, table=True):
    __tablename__ = "rvoes"
    __table_args__ = (
        UniqueConstraint("agreement_number", name="uq_rvoe_agreement"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    program_id: uuid.UUID = Field(foreign_key="programs.id", index=True)
    campus_id: uuid.UUID = Field(foreign_key="campuses.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)

    def is_operable(self) -> bool:
        """RT-03: only a 'vigente' RVOE allows groups, enrollments and official documents."""
        return self.status == RvoeStatus.vigente


class RvoeCreate(RvoeBase):
    program_id: uuid.UUID
    campus_id: uuid.UUID


class RvoeUpdate(SQLModel):
    agreement_number: str | None = None
    authority: RvoeAuthority | None = None
    issue_date: date | None = None
    valid_until: date | None = None
    status: RvoeStatus | None = None
    notes: str | None = None


class RvoePublic(RvoeBase):
    id: uuid.UUID
    program_id: uuid.UUID
    campus_id: uuid.UUID


# --- Plan versions and subjects (RT-04, RF-C07) ------------------------------

class PlanVersionBase(SQLModel):
    version_label: str = Field(max_length=32)  # e.g. "2024"
    period_type: PeriodType = PeriodType.cuatrimestral
    periods_count: int = Field(default=9, ge=1, le=20)  # semestres/cuatrimestres del plan
    min_attendance_pct: float = Field(default=80.0, ge=0, le=100)  # RF-A02, varies by modality via RVOE
    is_active: bool = True


class PlanVersion(PlanVersionBase, table=True):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("rvoe_id", "version_label", name="uq_plan_version"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    rvoe_id: uuid.UUID = Field(foreign_key="rvoes.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class PlanVersionCreate(PlanVersionBase):
    rvoe_id: uuid.UUID


class PlanVersionPublic(PlanVersionBase):
    id: uuid.UUID
    rvoe_id: uuid.UUID


class PlanSubjectBase(SQLModel):
    code: str = Field(max_length=32)
    name: str = Field(max_length=255)
    period_number: int = Field(ge=1, le=20)  # cuatrimestre/semestre en el mapa curricular
    credits: float = Field(ge=0)
    theory_hours: float = Field(default=0, ge=0)
    practice_hours: float = Field(default=0, ge=0)


class PlanSubject(PlanSubjectBase, table=True):
    __tablename__ = "plan_subjects"
    __table_args__ = (UniqueConstraint("plan_version_id", "code", name="uq_plan_subject_code"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    plan_version_id: uuid.UUID = Field(foreign_key="plan_versions.id", index=True)


class PlanSubjectCreate(PlanSubjectBase):
    plan_version_id: uuid.UUID
    prerequisite_ids: list[uuid.UUID] = []


class PlanSubjectPublic(PlanSubjectBase):
    id: uuid.UUID
    plan_version_id: uuid.UUID
    prerequisite_ids: list[uuid.UUID] = []


class SubjectPrerequisite(SQLModel, table=True):
    """Seriación (RF-C07): subject requires prerequisite passed before enrollment."""
    __tablename__ = "subject_prerequisites"
    subject_id: uuid.UUID = Field(foreign_key="plan_subjects.id", primary_key=True)
    prerequisite_id: uuid.UUID = Field(foreign_key="plan_subjects.id", primary_key=True)


# --- Terms (RT-06) ------------------------------------------------------------

class TermBase(SQLModel):
    name: str = Field(max_length=64)  # e.g. "2026-2 SEP-DIC"
    period_type: PeriodType = PeriodType.cuatrimestral
    start_date: date
    end_date: date
    is_open: bool = True  # never forces a formal "close" (RT-06)
    grade_capture_open: bool = False  # RF-C01: Servicios Escolares enables the capture window


class Term(TermBase, table=True):
    __tablename__ = "terms"
    __table_args__ = (UniqueConstraint("institution_id", "name", "period_type", name="uq_term_name"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class TermCreate(TermBase):
    pass


class TermUpdate(SQLModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_open: bool | None = None
    grade_capture_open: bool | None = None


class TermPublic(TermBase):
    id: uuid.UUID
    institution_id: uuid.UUID


# --- Groups (RT-03) -----------------------------------------------------------

class GroupBase(SQLModel):
    code: str = Field(max_length=32)  # e.g. "LD-3A"
    period_number: int = Field(default=1, ge=1, le=20)
    is_active: bool = True


class Group(GroupBase, table=True):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("term_id", "code", name="uq_group_code"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    plan_version_id: uuid.UUID = Field(foreign_key="plan_versions.id", index=True)
    term_id: uuid.UUID = Field(foreign_key="terms.id", index=True)
    campus_id: uuid.UUID = Field(foreign_key="campuses.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class GroupCreate(GroupBase):
    plan_version_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID


class GroupPublic(GroupBase):
    id: uuid.UUID
    plan_version_id: uuid.UUID
    term_id: uuid.UUID
    campus_id: uuid.UUID


class GroupSubjectBase(SQLModel):
    schedule_text: str = Field(default="", max_length=255)  # display-only; calendar system owns scheduling


class GroupSubject(GroupSubjectBase, table=True):
    """A subject taught in a group, optionally assigned to a teacher user (RF-C01)."""
    __tablename__ = "group_subjects"
    __table_args__ = (UniqueConstraint("group_id", "plan_subject_id", name="uq_group_subject"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_id: uuid.UUID = Field(foreign_key="groups.id", index=True)
    plan_subject_id: uuid.UUID = Field(foreign_key="plan_subjects.id", index=True)
    teacher_user_id: uuid.UUID | None = Field(default=None, foreign_key="users.id", index=True)


class GroupSubjectCreate(GroupSubjectBase):
    group_id: uuid.UUID
    plan_subject_id: uuid.UUID
    teacher_user_id: uuid.UUID | None = None


class GroupSubjectPublic(GroupSubjectBase):
    id: uuid.UUID
    group_id: uuid.UUID
    plan_subject_id: uuid.UUID
    teacher_user_id: uuid.UUID | None
