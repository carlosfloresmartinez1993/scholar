"""tablas propias para reconocimientos y cambios de RVOE (antes solo en la bitácora)

El kárdex dejaba de depender de audit_logs: los orígenes de EQ/REV/CONV y la cadena de
cambios de RVOE se copian aquí. La bitácora se conserva tal cual, como historial.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09 10:00:00.000000

"""
import json
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    recognitions = op.create_table(
        'subject_recognitions',
        sa.Column('subject_enrollment_id', sa.Uuid(), nullable=False),
        sa.Column('origin', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['subject_enrollment_id'], ['subject_enrollments.id']),
        sa.PrimaryKeyConstraint('subject_enrollment_id'),
    )
    changes = op.create_table(
        'plan_changes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('from_plan_enrollment_id', sa.Uuid(), nullable=True),
        sa.Column('to_plan_enrollment_id', sa.Uuid(), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('changed_by', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('reverted_at', sa.DateTime(), nullable=True),
        sa.Column('reverted_by', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('revert_reason', sa.String(length=255), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['student_id'], ['students.id']),
        sa.ForeignKeyConstraint(['from_plan_enrollment_id'], ['student_plan_enrollments.id']),
        sa.ForeignKeyConstraint(['to_plan_enrollment_id'], ['student_plan_enrollments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_plan_changes_student_id', 'plan_changes', ['student_id'])
    op.create_index('ix_plan_changes_from_plan_enrollment_id', 'plan_changes', ['from_plan_enrollment_id'])
    op.create_index('ix_plan_changes_to_plan_enrollment_id', 'plan_changes', ['to_plan_enrollment_id'])

    bind = op.get_bind()
    enrollments = {str(row.id) for row in bind.execute(sa.text('SELECT id FROM subject_enrollments'))}
    latest: dict[str, dict] = {}
    for row in bind.execute(sa.text(
        "SELECT entity_id, detail, created_at FROM audit_logs "
        "WHERE action = 'subject_enrollment.recognized' ORDER BY created_at"
    )):
        if row.entity_id in enrollments:  # the latest entry wins: a correction
            latest[row.entity_id] = {
                'subject_enrollment_id': uuid.UUID(row.entity_id),
                'origin': json.loads(row.detail or '{}').get('origin') or '',
                'updated_at': row.created_at,
            }
    if latest:
        op.bulk_insert(recognitions, list(latest.values()))

    plans = {str(row.id): row.student_id for row in bind.execute(
        sa.text('SELECT id, student_id FROM student_plan_enrollments'))}
    reverted = {row.entity_id: row for row in bind.execute(sa.text(
        "SELECT entity_id, actor, detail, created_at FROM audit_logs "
        "WHERE action = 'plan_enrollment.rvoe_change_reverted'"
    ))}
    rows = []
    for row in bind.execute(sa.text(
        "SELECT id, actor, entity_id, detail, created_at FROM audit_logs "
        "WHERE action = 'plan_enrollment.rvoe_changed' ORDER BY created_at"
    )):
        detail = json.loads(row.detail or '{}')
        source = detail.get('from_plan_enrollment_id')
        target = row.entity_id
        student_id = plans.get(target) or plans.get(source)
        if student_id is None:
            continue  # both plans gone: it only lives on in the audit log
        undone = reverted.get(str(row.id))
        rows.append({
            'id': row.id,  # same id: a reversal in flight still finds it
            'student_id': student_id,
            'from_plan_enrollment_id': uuid.UUID(source) if source in plans else None,
            'to_plan_enrollment_id': uuid.UUID(target) if target in plans else None,
            'detail': detail,
            'changed_by': row.actor,
            'created_at': row.created_at,
            'reverted_at': undone.created_at if undone else None,
            'reverted_by': undone.actor if undone else '',
            'revert_reason': (json.loads(undone.detail or '{}').get('reason') or '')[:255] if undone else '',
        })
    if rows:
        op.bulk_insert(changes, rows)


def downgrade() -> None:
    op.drop_table('plan_changes')
    op.drop_table('subject_recognitions')
