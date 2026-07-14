"""scholarship approval workflow + tolerance, institution fiscal data, fiscal profiles

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New scholarship statuses (native PG enum).
    op.execute("ALTER TYPE scholarshipstatus ADD VALUE IF NOT EXISTS 'solicitada'")
    op.execute("ALTER TYPE scholarshipstatus ADD VALUE IF NOT EXISTS 'suspendida'")

    # Institution fiscal data (receipt header).
    op.add_column('institutions', sa.Column('rfc', sa.String(length=13), nullable=False, server_default=''))
    op.add_column('institutions', sa.Column('fiscal_address', sa.String(length=512), nullable=False, server_default=''))

    # Scholarship: tolerance + request/authorization workflow.
    op.add_column('scholarships', sa.Column('tolerance_days', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scholarships', sa.Column('requested_by', sa.Uuid(), nullable=True))
    op.add_column('scholarships', sa.Column('authorized_at', sa.DateTime(), nullable=True))
    # Backfill requester from the historical approver, then require it.
    op.execute('UPDATE scholarships SET requested_by = approved_by WHERE requested_by IS NULL')
    op.alter_column('scholarships', 'requested_by', nullable=False)
    op.alter_column('scholarships', 'approved_by', nullable=True)
    op.create_foreign_key('fk_scholarships_requested_by', 'scholarships', 'users',
                          ['requested_by'], ['id'])

    # Student fiscal profiles.
    op.create_table(
        'student_fiscal_profiles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('rfc', sa.String(length=13), nullable=False),
        sa.Column('razon_social', sa.String(length=255), nullable=False),
        sa.Column('regimen_fiscal', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('uso_cfdi', sa.String(length=8), nullable=False, server_default='G03'),
        sa.Column('email', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('cp', sa.String(length=5), nullable=False, server_default=''),
        sa.Column('calle', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('no_ext', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('no_int', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('colonia', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('municipio', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('estado', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('pais', sa.String(length=64), nullable=False, server_default='México'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id'),
    )
    op.create_index(op.f('ix_student_fiscal_profiles_student_id'), 'student_fiscal_profiles',
                    ['student_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_student_fiscal_profiles_student_id'), table_name='student_fiscal_profiles')
    op.drop_table('student_fiscal_profiles')
    op.drop_constraint('fk_scholarships_requested_by', 'scholarships', type_='foreignkey')
    op.alter_column('scholarships', 'approved_by', nullable=False)
    op.drop_column('scholarships', 'authorized_at')
    op.drop_column('scholarships', 'requested_by')
    op.drop_column('scholarships', 'tolerance_days')
    op.drop_column('institutions', 'fiscal_address')
    op.drop_column('institutions', 'rfc')
    # Enum values are not dropped (Postgres can't remove enum values easily).
