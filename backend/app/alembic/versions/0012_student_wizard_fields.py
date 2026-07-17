"""student wizard fields: split name, birth data, domicilio, phones, academic
history + student_relatives table

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

sex = sa.Enum('F', 'M', name='sex')

_STUDENT_COLUMNS = [
    sa.Column('last_name_p', sa.String(length=100), nullable=True),
    sa.Column('last_name_m', sa.String(length=100), nullable=True),
    sa.Column('first_names', sa.String(length=100), nullable=True),
    sa.Column('sex', sex, nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('birth_country', sa.String(length=64), nullable=True),
    sa.Column('birth_state', sa.String(length=64), nullable=True),
    sa.Column('birth_place', sa.String(length=128), nullable=True),
    sa.Column('street', sa.String(length=128), nullable=True),
    sa.Column('ext_no', sa.String(length=16), nullable=True),
    sa.Column('int_no', sa.String(length=16), nullable=True),
    sa.Column('address_reference', sa.String(length=255), nullable=True),
    sa.Column('colonia', sa.String(length=128), nullable=True),
    sa.Column('municipio', sa.String(length=128), nullable=True),
    sa.Column('locality', sa.String(length=128), nullable=True),
    sa.Column('address_state', sa.String(length=64), nullable=True),
    sa.Column('address_country', sa.String(length=64), nullable=True),
    sa.Column('postal_code', sa.String(length=5), nullable=True),
    sa.Column('phone_home', sa.String(length=32), nullable=True),
    sa.Column('phone_work', sa.String(length=32), nullable=True),
    sa.Column('previous_school', sa.String(length=255), nullable=True),
    sa.Column('previous_gpa', sa.Float(), nullable=True),
    sa.Column('enrollment_notes', sa.String(length=1000), nullable=True),
]


def upgrade() -> None:
    sex.create(op.get_bind(), checkfirst=True)
    for column in _STUDENT_COLUMNS:
        op.add_column('students', column)
    op.create_table(
        'student_relatives',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('relationship', sa.String(length=32), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['student_id'], ['students.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_student_relatives_student_id'), 'student_relatives', ['student_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_student_relatives_student_id'), table_name='student_relatives')
    op.drop_table('student_relatives')
    for column in reversed(_STUDENT_COLUMNS):
        op.drop_column('students', column.name)
    sex.drop(op.get_bind(), checkfirst=True)
