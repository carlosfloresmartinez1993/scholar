"""user profile fields: display name, location, position, recovery email + code

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

userposition = sa.Enum(
    'control_escolar', 'directivo', 'cobranza', 'docente',
    'coordinacion_academica', 'direccion', 'sistemas', 'administrativo',
    name='userposition',
)


def upgrade() -> None:
    userposition.create(op.get_bind(), checkfirst=True)
    op.add_column('users', sa.Column('display_name', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('location', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('position', userposition, nullable=True))
    op.add_column('users', sa.Column('recovery_email', sa.String(length=255), nullable=True))
    op.add_column(
        'users',
        sa.Column('recovery_email_verified', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        'users', sa.Column('pending_recovery_email', sa.String(length=255), nullable=True)
    )
    op.add_column('users', sa.Column('recovery_code_hash', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('recovery_code_expires', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('recovery_code_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'recovery_code_sent_at')
    op.drop_column('users', 'recovery_code_expires')
    op.drop_column('users', 'recovery_code_hash')
    op.drop_column('users', 'pending_recovery_email')
    op.drop_column('users', 'recovery_email_verified')
    op.drop_column('users', 'recovery_email')
    op.drop_column('users', 'position')
    op.drop_column('users', 'location')
    op.drop_column('users', 'display_name')
    userposition.drop(op.get_bind(), checkfirst=True)
