"""pre-authorized scholarship percentages on institution

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-22 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('institutions', sa.Column('scholarship_pcts', sa.JSON(), nullable=False,
                                            server_default='[]'))


def downgrade() -> None:
    op.drop_column('institutions', 'scholarship_pcts')
