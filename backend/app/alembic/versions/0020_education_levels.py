"""niveles educativos como catálogo editable

The fixed enum (tsu … doctorado) becomes the education_levels table, one set per
institution; programs and document requirements keep the level's code as text.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-16 10:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULTS = [
    ("preescolar", "Preescolar", 10), ("primaria", "Primaria", 20), ("secundaria", "Secundaria", 30),
    ("bachillerato", "Bachillerato", 40), ("tsu", "TSU", 50), ("licenciatura", "Licenciatura", 60),
    ("especialidad", "Especialidad", 70), ("maestria", "Maestría", 80), ("doctorado", "Doctorado", 90),
]


def upgrade() -> None:
    levels = op.create_table(
        'education_levels',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('institution_id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('institution_id', 'code', name='uq_education_level_code'),
    )
    op.create_index('ix_education_levels_institution_id', 'education_levels', ['institution_id'])
    bind = op.get_bind()
    rows = [
        {"id": uuid.uuid4(), "institution_id": institution, "code": code, "name": name,
         "sort_order": order, "is_active": True}
        for (institution,) in bind.execute(sa.text("SELECT id FROM institutions"))
        for code, name, order in DEFAULTS
    ]
    if rows:
        op.bulk_insert(levels, rows)

    op.alter_column('programs', 'level', type_=sa.String(length=32),
                    postgresql_using='level::text', existing_nullable=False)
    op.alter_column('document_requirements', 'level', type_=sa.String(length=32),
                    postgresql_using='level::text', existing_nullable=True)
    op.execute("DROP TYPE IF EXISTS educationlevel")


def downgrade() -> None:
    levels = sa.Enum('tsu', 'licenciatura', 'especialidad', 'maestria', 'doctorado', name='educationlevel')
    levels.create(op.get_bind(), checkfirst=True)
    op.alter_column('programs', 'level', type_=levels, postgresql_using='level::educationlevel')
    op.alter_column('document_requirements', 'level', type_=levels,
                    postgresql_using='level::educationlevel')
    op.drop_table('education_levels')
