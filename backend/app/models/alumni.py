"""Egresados: read-only shapes for the alumni registry and its dashboard.

Nothing here is a table. Who graduated is already recorded — `Student.status`,
`StudentPlanEnrollment.status` and the libro de títulos (RF-C09) — and *when*
they graduated is derived from the last term they were enrolled in, so an
alumni row is a projection over rows that already exist rather than a new
place for the same fact to drift.
"""
import uuid
from datetime import date

from sqlmodel import SQLModel

from app.models.catalog import EducationLevel
from app.models.grades import DegreeKind
from app.models.student import PlanEnrollmentStatus, StudentStatus


class AlumniDegree(SQLModel):
    """The libro de títulos entry backing a row's «titulado»."""
    kind: DegreeKind
    folio: str
    issue_date: date
    program_name: str


class AlumniRow(SQLModel):
    """One graduate in one program. A student who finished two programs is two
    rows — «de qué egresó» is a property of the plan, not of the person."""
    student_id: uuid.UUID
    enrollment_number: str
    full_name: str
    curp: str
    email: str
    campus_id: uuid.UUID
    student_status: StudentStatus
    has_photo: bool = False
    # Null for a student marked egresado who was never enrolled in a plan. Such
    # a row is incomplete, not absent: dropping it would quietly shrink the count.
    plan_enrollment_id: uuid.UUID | None = None
    plan_enrollment_status: PlanEnrollmentStatus | None = None
    program_id: uuid.UUID | None = None
    program_name: str | None = None
    level: EducationLevel | None = None
    plan_version_label: str | None = None
    rvoe: str | None = None
    # Derived: the last term the student held a group enrollment in. Null when
    # they never had one (imported record, or marked egresado by hand).
    egreso_term_id: uuid.UUID | None = None
    egreso_term_name: str | None = None
    egreso_date: date | None = None
    titulado: bool = False
    degree: AlumniDegree | None = None


class AlumniTermBucket(SQLModel):
    term_id: uuid.UUID | None = None
    term_name: str  # "Sin periodo" for the rows with no enrollment history
    end_date: date | None = None
    egresados: int
    titulados: int


class AlumniProgramBucket(SQLModel):
    program_id: uuid.UUID | None = None
    program_name: str  # "Sin plan" for egresados with no plan enrollment
    level: EducationLevel | None = None
    egresados: int
    titulados: int


class AlumniStats(SQLModel):
    """Counts are of DISTINCT STUDENTS, not of rows: someone who finished two
    programs is one egresado. The per-term and per-program buckets count rows,
    because that is the question those breakdowns answer."""
    egresados: int
    titulados: int
    titulacion_pct: float
    rows: int
    sin_periodo: int
    sin_plan: int
    by_term: list[AlumniTermBucket]
    by_program: list[AlumniProgramBucket]
