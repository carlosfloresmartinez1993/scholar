"""group uniqueness includes campus (Servo Grupo key = Ciclo, Plantel, Clave)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen group uniqueness from (term, code) to (term, campus, code)."""
    op.drop_constraint('uq_group_code', 'groups', type_='unique')
    op.create_unique_constraint('uq_group_code', 'groups', ['term_id', 'campus_id', 'code'])


def downgrade() -> None:
    op.drop_constraint('uq_group_code', 'groups', type_='unique')
    op.create_unique_constraint('uq_group_code', 'groups', ['term_id', 'code'])
