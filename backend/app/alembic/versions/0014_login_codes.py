"""email-code login columns (hash-only, never the plain code)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('login_code_hash', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('login_code_expires', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('login_code_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'login_code_sent_at')
    op.drop_column('users', 'login_code_expires')
    op.drop_column('users', 'login_code_hash')
