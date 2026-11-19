"""materias reprobadas permitidas para avanzar de cuatrimestre

The institution's rule (reglamento): a student may move on to the next
cuatrimestre with up to N subjects of the one that ends failed. 0 = all passed
(the behaviour until now).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0024'
down_revision: Union[str, Sequence[str], None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'institutions',
        sa.Column('max_failed_to_promote', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('institutions', 'max_failed_to_promote')
