import uuid
from datetime import datetime
from enum import Enum

from app.models.common import utcnow

from pydantic import EmailStr
from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    """RT-07: staff roles. Students are not users in this iteration (portal later);
    superusers bypass role checks."""
    admin_sistema = "admin_sistema"
    direccion = "direccion"
    servicios_escolares = "servicios_escolares"
    coordinador_academico = "coordinador_academico"
    tesoreria = "tesoreria"
    docente = "docente"


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


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(SQLModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime
    recovery_email: str | None = None
    recovery_email_verified: bool = False
    pending_recovery_email: str | None = None


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
