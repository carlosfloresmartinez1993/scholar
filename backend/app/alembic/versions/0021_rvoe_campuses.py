"""un RVOE puede aplicar en varios planteles

The RVOE keeps its main campus (rvoes.campus_id); rvoe_campuses lists the other
planteles where the same RVOE (same plan) is offered. Each group belongs to one
of them.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rvoe_campuses',
        sa.Column('rvoe_id', sa.Uuid(), nullable=False),
        sa.Column('campus_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['rvoe_id'], ['rvoes.id']),
        sa.ForeignKeyConstraint(['campus_id'], ['campuses.id']),
        sa.PrimaryKeyConstraint('rvoe_id', 'campus_id'),
    )
    op.create_index('ix_rvoe_campuses_campus_id', 'rvoe_campuses', ['campus_id'])


def downgrade() -> None:
    op.drop_table('rvoe_campuses')
