"""fiscal receptor registry (recurrent invoicing clients)

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-22 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fiscal_receptors',
        sa.Column('id', sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fiscal_receptors_rfc'), 'fiscal_receptors', ['rfc'], unique=True)

    # Seed the registry from fiscal data already captured per student (latest wins).
    op.execute("""
        INSERT INTO fiscal_receptors (id, rfc, razon_social, regimen_fiscal, uso_cfdi,
            email, cp, calle, no_ext, no_int, colonia, municipio, estado, pais,
            created_at, updated_at)
        SELECT DISTINCT ON (rfc) id, rfc, razon_social, regimen_fiscal, uso_cfdi,
            email, cp, calle, no_ext, no_int, colonia, municipio, estado, pais,
            created_at, updated_at
        FROM student_fiscal_profiles
        WHERE rfc <> ''
        ORDER BY rfc, updated_at DESC
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_fiscal_receptors_rfc'), table_name='fiscal_receptors')
    op.drop_table('fiscal_receptors')
