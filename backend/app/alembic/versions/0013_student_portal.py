"""student portal: alumno role + users.student_id link

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-17 12:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG 12+: ADD VALUE works inside the migration transaction (the value is
    # only used by later transactions).
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'alumno'")
    op.add_column('users', sa.Column('student_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_users_student_id', 'users', 'students', ['student_id'], ['id']
    )
    op.create_unique_constraint('uq_users_student_id', 'users', ['student_id'])


def downgrade() -> None:
    op.drop_constraint('uq_users_student_id', 'users', type_='unique')
    op.drop_constraint('fk_users_student_id', 'users', type_='foreignkey')
    op.drop_column('users', 'student_id')
    # the 'alumno' enum value is left in place: removing a value requires
    # rebuilding the type, and an unused value is harmless (re-upgrade is
    # idempotent via IF NOT EXISTS).
