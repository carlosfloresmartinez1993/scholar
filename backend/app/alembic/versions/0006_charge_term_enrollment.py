"""tie charges to term + group enrollment (auto-billing)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Auto-billing (RF-T02): a charge can belong to the term/enrollment it was
    generated for, so a repeated cuatrimestre gets its own fresh charges."""
    op.add_column('charges', sa.Column('term_id', sa.Uuid(), nullable=True))
    op.add_column('charges', sa.Column('group_enrollment_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_charges_term_id', 'charges', 'terms', ['term_id'], ['id']
    )
    op.create_foreign_key(
        'fk_charges_group_enrollment_id', 'charges', 'group_enrollments',
        ['group_enrollment_id'], ['id'],
    )
    op.create_index('ix_charges_term_id', 'charges', ['term_id'])
    op.create_index('ix_charges_group_enrollment_id', 'charges', ['group_enrollment_id'])


def downgrade() -> None:
    op.drop_index('ix_charges_group_enrollment_id', table_name='charges')
    op.drop_index('ix_charges_term_id', table_name='charges')
    op.drop_constraint('fk_charges_group_enrollment_id', 'charges', type_='foreignkey')
    op.drop_constraint('fk_charges_term_id', 'charges', type_='foreignkey')
    op.drop_column('charges', 'group_enrollment_id')
    op.drop_column('charges', 'term_id')
