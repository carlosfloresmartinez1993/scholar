"""link a group to the previous-term group it promotes from

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The previous-term group whose passing students promote into this one —
    the explicit link the cycle-promotion cron follows."""
    op.add_column('groups', sa.Column('promotes_from_group_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_groups_promotes_from', 'groups', 'groups',
        ['promotes_from_group_id'], ['id'],
    )
    # a source group promotes into at most one next-term group
    op.create_unique_constraint(
        'uq_group_promotes_from', 'groups', ['promotes_from_group_id']
    )


def downgrade() -> None:
    op.drop_constraint('uq_group_promotes_from', 'groups', type_='unique')
    op.drop_constraint('fk_groups_promotes_from', 'groups', type_='foreignkey')
    op.drop_column('groups', 'promotes_from_group_id')
