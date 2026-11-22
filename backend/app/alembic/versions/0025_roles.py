"""roles editables desde Scholar (Etapa 1: qué vistas ve cada rol)

Creates roles + role_permissions with the system roles and the views each one
could already open, and turns users.role into a plain code (VARCHAR) so new
roles can be created from the interface.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-22 18:00:00.000000

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0025'
down_revision: Union[str, Sequence[str], None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALL = [
    "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
    "calificaciones", "asistencias", "tesoreria", "reportes", "periodos", "planteles",
    "configuracion", "usuarios", "auditoria", "roles", "becas_autorizar",
]
DEFAULTS = [
    ("admin_sistema", "Administrador de sistema", False, ALL),
    ("direccion", "Dirección", False, [
        "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
        "calificaciones", "asistencias", "tesoreria", "reportes", "periodos", "planteles",
        "configuracion", "becas_autorizar"]),
    ("servicios_escolares", "Servicios Escolares", False, [
        "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
        "calificaciones", "asistencias", "periodos", "planteles", "configuracion"]),
    ("coordinador_academico", "Coordinación académica", False, [
        "inicio", "alumnos", "grupos", "egresados", "calificaciones", "asistencias"]),
    ("tesoreria", "Tesorería", False, ["inicio", "tesoreria", "reportes"]),
    ("docente", "Docente", True, ["calificaciones", "asistencias"]),
]


def upgrade() -> None:
    roles = op.create_table(
        'roles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('own_subjects_only', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_roles_code', 'roles', ['code'], unique=True)
    perms = op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('permission', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id']),
        sa.PrimaryKeyConstraint('role_id', 'permission'),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    role_rows, perm_rows = [], []
    for code, name, own, permissions in DEFAULTS:
        role_id = uuid.uuid4()
        role_rows.append({"id": role_id, "code": code, "name": name, "description": "",
                          "is_system": True, "own_subjects_only": own, "is_active": True,
                          "created_at": now})
        perm_rows += [{"role_id": role_id, "permission": p} for p in permissions]
    op.bulk_insert(roles, role_rows)
    op.bulk_insert(perms, perm_rows)

    # users.role: from a fixed enum to a role code (new roles come from the interface)
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(64) USING role::text")
    op.execute("DROP TYPE IF EXISTS userrole")


def downgrade() -> None:
    op.execute(
        "CREATE TYPE userrole AS ENUM ('admin_sistema', 'direccion', 'servicios_escolares', "
        "'coordinador_academico', 'tesoreria', 'docente', 'alumno')"
    )
    op.execute("UPDATE users SET role = 'docente' WHERE role NOT IN ('admin_sistema', 'direccion', "
               "'servicios_escolares', 'coordinador_academico', 'tesoreria', 'docente', 'alumno')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole")
    op.drop_table('role_permissions')
    op.drop_index('ix_roles_code', table_name='roles')
    op.drop_table('roles')
