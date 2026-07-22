import uuid
from datetime import datetime
from enum import Enum

from app.models.common import utcnow

from pydantic import EmailStr
from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    """RT-07: staff roles + the student portal role. Staff guards are explicit
    role lists (see api/deps.py), so `alumno` never passes them; superusers
    bypass role checks."""
    admin_sistema = "admin_sistema"
    direccion = "direccion"
    servicios_escolares = "servicios_escolares"
    coordinador_academico = "coordinador_academico"
    tesoreria = "tesoreria"
    docente = "docente"
    alumno = "alumno"


class UserPosition(str, Enum):
    """Job position shown on the profile (informative; roles govern permissions)."""
    control_escolar = "control_escolar"
    directivo = "directivo"
    cobranza = "cobranza"
    docente = "docente"
    coordinacion_academica = "coordinacion_academica"
    direccion = "direccion"
    sistemas = "sistemas"
    administrativo = "administrativo"


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    full_name: str = Field(max_length=255)
    role: UserRole = UserRole.docente
    is_active: bool = True
    is_superuser: bool = False
    display_name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    position: UserPosition | None = None


class User(UserBase, table=True):
    __tablename__ = "users"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=utcnow)
    # role=alumno accounts are linked 1:1 to their student row (portal access)
    student_id: uuid.UUID | None = Field(
        default=None, foreign_key="students.id", unique=True
    )
    # Recovery email + 6-digit verification code (hash only, never the code).
    # A new address lands in pending_recovery_email and only replaces
    # recovery_email once its code is verified — a failed/abandoned attempt
    # never clobbers the previously verified address.
    recovery_email: str | None = Field(default=None, max_length=255)
    recovery_email_verified: bool = False
    pending_recovery_email: str | None = Field(default=None, max_length=255)
    recovery_code_hash: str | None = Field(default=None, max_length=64)
    recovery_code_expires: datetime | None = None
    recovery_code_sent_at: datetime | None = None
    # Email-code login: only the sha256 of the 6-digit code is stored.
    login_code_hash: str | None = Field(default=None, max_length=64)
    login_code_expires: datetime | None = None
    login_code_sent_at: datetime | None = None


class UserCampus(SQLModel, table=True):
    """Campus membership (the scope axis, orthogonal to role). A user sees the
    campus-tier resources of the campuses they belong to. Superusers and
    admin_sistema are implicitly all-campus and don't need rows here — but the
    backfill still grants them every campus so nothing is lost on downgrade."""
    __tablename__ = "user_campuses"
    user_id: uuid.UUID = Field(foreign_key="users.id", primary_key=True)
    campus_id: uuid.UUID = Field(foreign_key="campuses.id", primary_key=True)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    # campus membership to grant (ignored for all-campus roles); None = none
    campuses: list[uuid.UUID] | None = None


class UserUpdate(SQLModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    # when provided, replaces the user's whole campus membership set
    campuses: list[uuid.UUID] | None = None


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime
    recovery_email: str | None = None
    recovery_email_verified: bool = False
    pending_recovery_email: str | None = None
    student_id: uuid.UUID | None = None
    # campus scope (computed): the campuses this user may act on. all_campuses
    # means role/superuser grants every campus (campuses lists them all).
    campuses: list[uuid.UUID] = []
    all_campuses: bool = False


class ProfileUpdate(SQLModel):
    """Self-service profile edits (PATCH /users/me/profile)."""
    display_name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    position: UserPosition | None = None
    email: EmailStr | None = None
    # required (and verified) only when changing the primary email
    current_password: str | None = None


class RecoveryEmailRequest(SQLModel):
    email: EmailStr


class RecoveryEmailVerify(SQLModel):
    code: str = Field(min_length=6, max_length=6)
