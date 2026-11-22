"""roles Etapa 2: «ver» y «editar» por pantalla, y acciones delicadas

Every role keeps what it could already do: a view it had becomes «ver y editar»,
and it gets the delicate actions that came with its views (corregir kárdex and
cambio de RVOE with Alumnos, promoción with Grupos, actas with Calificaciones for
roles that are not limited to their own materias, cancelar pagos with Tesorería).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0026'
down_revision: Union[str, Sequence[str], None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EDITABLE = [
    "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
    "calificaciones", "asistencias", "tesoreria", "periodos", "planteles", "configuracion",
    "usuarios", "roles",
]
# (special action, the view it came with, only for roles not limited to their materias)
SPECIALS = [
    ("kardex_corregir", "alumnos", True),
    ("rvoe_cambio", "alumnos", True),
    ("promocion_ciclo", "grupos", True),
    ("actas", "calificaciones", True),
    ("pagos_cancelar", "tesoreria", True),
]


def upgrade() -> None:
    for view in EDITABLE:
        op.execute(
            f"INSERT INTO role_permissions (role_id, permission) "
            f"SELECT role_id, '{view}.editar' FROM role_permissions WHERE permission = '{view}' "
            f"ON CONFLICT DO NOTHING"
        )
    for action, view, staff_only in SPECIALS:
        only = " AND r.own_subjects_only = false" if staff_only else ""
        op.execute(
            f"INSERT INTO role_permissions (role_id, permission) "
            f"SELECT rp.role_id, '{action}' FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            f"WHERE rp.permission = '{view}'{only} ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission LIKE '%.editar'")
    op.execute(
        "DELETE FROM role_permissions WHERE permission IN "
        "('kardex_corregir', 'rvoe_cambio', 'promocion_ciclo', 'actas', 'pagos_cancelar')"
    )
