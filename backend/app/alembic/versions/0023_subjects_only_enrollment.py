"""materia en otro grupo: inscripción solo de materias, sin cargos

A student in 7th can take a pending subject in another group that teaches it.
That group enrollment is "subjects only": it does not change the student's
group, is not promoted and is not billed.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0023'
down_revision: Union[str, Sequence[str], None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'group_enrollments',
        sa.Column('subjects_only', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('group_enrollments', 'subjects_only')
