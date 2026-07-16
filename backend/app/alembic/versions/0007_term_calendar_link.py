"""link terms to the calendar system

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Link a scholar term to a calendar term (no FK: other database). When set,
    the calendar is the source of truth for the period's dates."""
    op.add_column('terms', sa.Column('calendar_term_id', sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        'uq_term_calendar', 'terms', ['institution_id', 'calendar_term_id']
    )


def downgrade() -> None:
    op.drop_constraint('uq_term_calendar', 'terms', type_='unique')
    op.drop_column('terms', 'calendar_term_id')
