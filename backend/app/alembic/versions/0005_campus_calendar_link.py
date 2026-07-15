"""link campuses to the calendar system

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Link scholar campuses to calendar campuses (no FK: other database)."""
    op.add_column('campuses', sa.Column('calendar_campus_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column('campuses', 'calendar_campus_id')
