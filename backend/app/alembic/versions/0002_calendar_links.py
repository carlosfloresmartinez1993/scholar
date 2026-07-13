"""calendar links

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: link programs/groups to the calendar system (no FK)."""
    op.add_column('programs', sa.Column('calendar_program_id', sa.Uuid(), nullable=True))
    op.add_column('groups', sa.Column('calendar_group_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('groups', 'calendar_group_id')
    op.drop_column('programs', 'calendar_program_id')
