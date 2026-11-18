"""logo de cada plantel (va arriba en el kárdex de sus alumnos)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0022'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campuses', sa.Column('logo_path', sa.String(length=1024), nullable=True))
    op.add_column('campuses', sa.Column('logo_content_type', sa.String(length=64), nullable=True))
    op.add_column('campuses', sa.Column('logo_updated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('campuses', 'logo_updated_at')
    op.drop_column('campuses', 'logo_content_type')
    op.drop_column('campuses', 'logo_path')
