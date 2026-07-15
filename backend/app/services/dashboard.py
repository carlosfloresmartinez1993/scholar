"""Inicio dashboard: per-level headcounts (activos, grupos, becados) and cartera
vencida for the open term, each with a delta vs the previous term."""
import uuid
from datetime import date

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    AbsenceJustification,
    Charge,
    ChargeStatus,
    EducationLevel,
    GradeActa,
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    GroupSubject,
    JustificationStatus,
    PlanVersion,
    Program,
    Rvoe,
    Scholarship,
    ScholarshipStatus,
    Student,
    StudentStatus,
    Term,
)
from app.models.common import utcnow
from app.services.treasury import charges_paid_map

LEVEL_ORDER = list(EducationLevel)

# Groups → their program level, shared join chain used by every per-level count.
_LEVEL_JOINS = (
    (PlanVersion, PlanVersion.id == Group.plan_version_id),
    (Rvoe, Rvoe.id == PlanVersion.rvoe_id),
    (Program, Program.id == Rvoe.program_id),
)


def _apply_level_joins(stmt):
    for model, on in _LEVEL_JOINS:
        stmt = stmt.join(model, on)
    return stmt


async def _students_by_level(session: AsyncSession, term_id: uuid.UUID) -> dict[str, int]:
    stmt = _apply_level_joins(
        select(Program.level, func.count(func.distinct(Student.id)))
        .select_from(GroupEnrollment)
        .join(Group, Group.id == GroupEnrollment.group_id)
        .join(Student, Student.id == GroupEnrollment.student_id)
    ).where(
        Group.term_id == term_id,
        GroupEnrollment.status == GroupEnrollmentStatus.activa,
        Student.status == StudentStatus.activo,
    ).group_by(Program.level)
    return {level: count for level, count in (await session.exec(stmt)).all()}


async def _groups_by_level(session: AsyncSession, term_id: uuid.UUID) -> dict[str, int]:
    stmt = _apply_level_joins(
        select(Program.level, func.count(func.distinct(Group.id))).select_from(Group)
    ).where(Group.term_id == term_id, Group.is_active == True).group_by(Program.level)  # noqa: E712
    return {level: count for level, count in (await session.exec(stmt)).all()}


async def _scholars_by_level(session: AsyncSession, term_id: uuid.UUID) -> dict[str, int]:
    stmt = _apply_level_joins(
        select(Program.level, func.count(func.distinct(Student.id)))
        .select_from(GroupEnrollment)
        .join(Group, Group.id == GroupEnrollment.group_id)
        .join(Student, Student.id == GroupEnrollment.student_id)
        .join(Scholarship, Scholarship.student_id == Student.id)
    ).where(
        Group.term_id == term_id,
        GroupEnrollment.status == GroupEnrollmentStatus.activa,
        Student.status == StudentStatus.activo,
        Scholarship.status == ScholarshipStatus.activa,
    ).group_by(Program.level)
    return {level: count for level, count in (await session.exec(stmt)).all()}


async def _cartera_vencida(session: AsyncSession, term: Term, today: date) -> float:
    """Unpaid net of charges due within the term and already past due. Iterates
    charges — bounded by one term's volume (ponytail: fine at institution scale)."""
    charges = (
        await session.exec(
            select(Charge).where(
                Charge.due_date >= term.start_date,
                Charge.due_date <= term.end_date,
                Charge.due_date < today,
                Charge.status.in_([ChargeStatus.pendiente, ChargeStatus.parcial]),  # type: ignore[attr-defined]
            )
        )
    ).all()
    paid_map = await charges_paid_map(session, [c.id for c in charges])
    total = sum(
        max(c.amount - c.scholarship_discount - paid_map.get(c.id, 0.0), 0.0) for c in charges
    )
    return round(total, 2)


async def _pending_tasks(session: AsyncSession, open_term_id: uuid.UUID) -> dict:
    """Actionable backlog for the work queue: what's waiting on staff right now."""
    justifications = await session.scalar(
        select(func.count())
        .select_from(AbsenceJustification)
        .where(AbsenceJustification.status == JustificationStatus.pendiente)
    )
    unsigned_actas = await session.scalar(
        select(func.count()).select_from(GradeActa).where(GradeActa.signed_at.is_(None))  # type: ignore[union-attr]
    )
    # group-subjects of the open term with no teacher assigned
    groups_without_teacher = await session.scalar(
        select(func.count())
        .select_from(GroupSubject)
        .join(Group, Group.id == GroupSubject.group_id)
        .where(Group.term_id == open_term_id, GroupSubject.teacher_user_id.is_(None))  # type: ignore[union-attr]
    )
    return {
        "justifications_pending": justifications or 0,
        "unsigned_actas": unsigned_actas or 0,
        "groups_without_teacher": groups_without_teacher or 0,
    }


async def dashboard_stats(session: AsyncSession, today: date | None = None) -> dict:
    today = today or utcnow().date()
    terms = (
        await session.exec(select(Term).order_by(Term.start_date.desc()))  # type: ignore[attr-defined]
    ).all()
    open_term = next((t for t in terms if t.is_open), terms[0] if terms else None)
    prev_term = None
    if open_term:
        prev_term = next((t for t in terms if t.start_date < open_term.start_date), None)

    def _levels_payload(cur: dict, prev: dict) -> dict:
        return {level: {"current": cur.get(level, 0), "previous": prev.get(level, 0)}
                for level in [l.value for l in LEVEL_ORDER]}

    if open_term is None:
        empty = {level.value: {"current": 0, "previous": 0} for level in LEVEL_ORDER}
        return {
            "term": None, "prev_term": None,
            "students": empty, "groups": empty, "scholars": empty,
            "cartera_vencida": {"current": 0.0, "previous": 0.0},
            "pending": {"justifications_pending": 0, "unsigned_actas": 0,
                        "groups_without_teacher": 0},
        }

    cur_students = await _students_by_level(session, open_term.id)
    cur_groups = await _groups_by_level(session, open_term.id)
    cur_scholars = await _scholars_by_level(session, open_term.id)
    prev_students = await _students_by_level(session, prev_term.id) if prev_term else {}
    prev_groups = await _groups_by_level(session, prev_term.id) if prev_term else {}
    prev_scholars = await _scholars_by_level(session, prev_term.id) if prev_term else {}

    return {
        "term": {"id": str(open_term.id), "name": open_term.name},
        "prev_term": {"id": str(prev_term.id), "name": prev_term.name} if prev_term else None,
        "students": _levels_payload(cur_students, prev_students),
        "groups": _levels_payload(cur_groups, prev_groups),
        "scholars": _levels_payload(cur_scholars, prev_scholars),
        "cartera_vencida": {
            "current": await _cartera_vencida(session, open_term, today),
            "previous": await _cartera_vencida(session, prev_term, today) if prev_term else 0.0,
        },
        "pending": await _pending_tasks(session, open_term.id),
    }
