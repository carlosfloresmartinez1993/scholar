"""student photo: portrait captured at the front desk (photo_path on students)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('students', sa.Column('photo_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('students', 'photo_path')
