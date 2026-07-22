"""condonaciones on charges + concept-scoped scholarships

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('charges', sa.Column('condoned_amount', sa.Float(), nullable=False, server_default='0'))
    op.add_column('charges', sa.Column('condoned_reason', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('scholarships', sa.Column('concept_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_scholarships_concept_id', 'scholarships', 'charge_concepts',
                          ['concept_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_scholarships_concept_id', 'scholarships', type_='foreignkey')
    op.drop_column('scholarships', 'concept_id')
    op.drop_column('charges', 'condoned_reason')
    op.drop_column('charges', 'condoned_amount')
