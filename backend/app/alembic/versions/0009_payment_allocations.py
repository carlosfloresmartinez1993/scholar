"""payment allocations: one payment (one folio/receipt) settles many charges

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Split table so a single cobro covers several charges (RF-T03)."""
    op.create_table(
        'payment_allocations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('payment_id', sa.Uuid(), nullable=False),
        sa.Column('charge_id', sa.Uuid(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id']),
        sa.ForeignKeyConstraint(['charge_id'], ['charges.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('payment_id', 'charge_id', name='uq_payment_allocation'),
    )
    op.create_index(
        op.f('ix_payment_allocations_payment_id'), 'payment_allocations', ['payment_id']
    )
    op.create_index(
        op.f('ix_payment_allocations_charge_id'), 'payment_allocations', ['charge_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_payment_allocations_charge_id'), table_name='payment_allocations')
    op.drop_index(op.f('ix_payment_allocations_payment_id'), table_name='payment_allocations')
    op.drop_table('payment_allocations')
