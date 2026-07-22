"""user_campuses: per-user campus membership (scope axis) + all-campus backfill

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_campuses',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('campus_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['campus_id'], ['campuses.id']),
        sa.PrimaryKeyConstraint('user_id', 'campus_id'),
    )
    # Backfill: every existing user gets membership to every existing campus, so
    # enabling enforcement locks nobody out (all-campus roles ignore these rows
    # but keeping them means a demotion doesn't silently strip access either).
    op.execute(
        "INSERT INTO user_campuses (user_id, campus_id) "
        "SELECT u.id, c.id FROM users u CROSS JOIN campuses c"
    )


def downgrade() -> None:
    op.drop_table('user_campuses')
