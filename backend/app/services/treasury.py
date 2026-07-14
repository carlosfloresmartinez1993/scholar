"""Treasury business rules: balances and statements (RF-T04), scholarship
application (RF-T05), late fees (RF-T06), debt blocking (RF-T07) and payment
allocation (RF-T03)."""
import uuid
from datetime import date, timedelta

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Charge,
    ChargePublic,
    ChargeStatus,
    Institution,
    Payment,
    Scholarship,
    ScholarshipStatus,
    Student,
)
from app.models.common import utcnow


async def charge_paid_amount(session: AsyncSession, charge_id: uuid.UUID) -> float:
    paid = (
        await session.exec(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.charge_id == charge_id, Payment.cancelled == False  # noqa: E712
            )
        )
    ).one()
    return float(paid)


async def charges_paid_map(
    session: AsyncSession, charge_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """Paid (non-cancelled) totals for many charges in one grouped query."""
    if not charge_ids:
        return {}
    rows = (
        await session.exec(
            select(Payment.charge_id, func.sum(Payment.amount))
            .where(
                Payment.charge_id.in_(charge_ids),  # type: ignore[attr-defined]
                Payment.cancelled == False,  # noqa: E712
            )
            .group_by(Payment.charge_id)
        )
    ).all()
    return {charge_id: float(paid) for charge_id, paid in rows}


def _net(charge: Charge) -> float:
    return max(charge.amount - charge.scholarship_discount, 0.0)


async def refresh_charge_status(session: AsyncSession, charge: Charge) -> Charge:
    if charge.status == ChargeStatus.cancelado:
        return charge
    paid = await charge_paid_amount(session, charge.id)
    if paid >= _net(charge) - 0.005:
        charge.status = ChargeStatus.pagado
    elif paid > 0:
        charge.status = ChargeStatus.parcial
    else:
        charge.status = ChargeStatus.pendiente
    session.add(charge)
    return charge


async def student_charges_public(session: AsyncSession, student_id: uuid.UUID) -> list[ChargePublic]:
    charges = (
        await session.exec(
            select(Charge).where(Charge.student_id == student_id).order_by(Charge.due_date)
        )
    ).all()
    paid_map = await charges_paid_map(session, [c.id for c in charges])
    out = []
    for c in charges:
        paid = paid_map.get(c.id, 0.0)
        pub = ChargePublic(
            id=c.id,
            student_id=c.student_id,
            concept_id=c.concept_id,
            description=c.description,
            amount=c.amount,
            scholarship_discount=c.scholarship_discount,
            due_date=c.due_date,
            status=c.status,
            is_late_fee=c.is_late_fee,
            paid_amount=paid,
            balance=max(_net(c) - paid, 0.0) if c.status != ChargeStatus.cancelado else 0.0,
        )
        out.append(pub)
    return out


async def overdue_balance(session: AsyncSession, student_id: uuid.UUID, today: date | None = None) -> float:
    """RF-T07: sum of unpaid net amounts past due date."""
    today = today or utcnow().date()
    charges = (
        await session.exec(
            select(Charge).where(
                Charge.student_id == student_id,
                Charge.due_date < today,
                Charge.status.in_([ChargeStatus.pendiente, ChargeStatus.parcial]),  # type: ignore[attr-defined]
            )
        )
    ).all()
    total = 0.0
    for c in charges:
        total += max(_net(c) - await charge_paid_amount(session, c.id), 0.0)
    return round(total, 2)


async def has_blocking_debt(session: AsyncSession, student: Student) -> bool:
    institution = await session.get(Institution, student.institution_id)
    if institution is None or not institution.block_documents_on_debt:
        return False
    return await overdue_balance(session, student.id) > 0


async def active_scholarship_discount(
    session: AsyncSession, student_id: uuid.UUID, amount: float, on: date
) -> float:
    """RF-T05: best active scholarship applied to one charge amount."""
    scholarships = (
        await session.exec(
            select(Scholarship).where(
                Scholarship.student_id == student_id,
                Scholarship.status == ScholarshipStatus.activa,
            )
        )
    ).all()
    best = 0.0
    for s in scholarships:
        if s.valid_from > on or (s.valid_to and s.valid_to < on):
            continue
        discount = amount * (s.pct / 100) if s.pct is not None else (s.fixed_amount or 0.0)
        best = max(best, min(discount, amount))
    return round(best, 2)


async def apply_late_fees(
    session: AsyncSession, institution: Institution, created_by: uuid.UUID, today: date | None = None
) -> int:
    """RF-T06: creates a recargo charge for each overdue charge without one.
    Returns the number of late fees created. Caller commits."""
    if institution.late_fee_pct <= 0:
        return 0
    today = today or utcnow().date()
    cutoff = today - timedelta(days=institution.late_fee_grace_days)
    overdue = (
        await session.exec(
            select(Charge)
            .join(Student, Student.id == Charge.student_id)
            .where(
                Student.institution_id == institution.id,
                Charge.due_date < cutoff,
                Charge.is_late_fee == False,  # noqa: E712
                Charge.status.in_([ChargeStatus.pendiente, ChargeStatus.parcial]),  # type: ignore[attr-defined]
            )
        )
    ).all()
    existing = set(
        (
            await session.exec(
                select(Charge.source_charge_id).where(Charge.is_late_fee == True)  # noqa: E712
            )
        ).all()
    )
    created = 0
    for charge in overdue:
        if charge.id in existing:
            continue
        remaining = max(_net(charge) - await charge_paid_amount(session, charge.id), 0.0)
        if remaining <= 0:
            continue
        session.add(
            Charge(
                student_id=charge.student_id,
                description=f"Recargo — {charge.description}",
                amount=round(remaining * institution.late_fee_pct / 100, 2),
                due_date=today,
                is_late_fee=True,
                source_charge_id=charge.id,
                created_by=created_by,
            )
        )
        created += 1
    return created
