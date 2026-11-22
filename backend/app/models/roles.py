"""Roles editable from Scholar (Administración → Roles): each one grants a set of
permissions (the views of app.core.permissions). Users point at a role by code."""
import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.common import utcnow


class Role(SQLModel, table=True):
    __tablename__ = "roles"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(max_length=64, unique=True, index=True)
    name: str = Field(max_length=128)
    description: str = Field(default="", max_length=512)
    # system roles come with Scholar: they can be edited, not deleted
    is_system: bool = False
    # like a docente: only the groups and materias assigned to them
    own_subjects_only: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class RolePermission(SQLModel, table=True):
    __tablename__ = "role_permissions"
    role_id: uuid.UUID = Field(foreign_key="roles.id", primary_key=True)
    permission: str = Field(max_length=64, primary_key=True)


class RolePublic(SQLModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    is_system: bool
    own_subjects_only: bool
    is_active: bool
    permissions: list[str] = []
    users_count: int = 0


class RoleCreate(SQLModel):
    name: str = Field(min_length=2, max_length=128)
    description: str = Field(default="", max_length=512)
    own_subjects_only: bool = False
    permissions: list[str] = []


class RoleUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    own_subjects_only: bool | None = None
    is_active: bool | None = None
    permissions: list[str] | None = None
