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


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    full_name: str = Field(max_length=255)
    role: UserRole = UserRole.docente
    is_active: bool = True
    is_superuser: bool = False


class User(UserBase, table=True):
    __tablename__ = "users"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=utcnow)


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
