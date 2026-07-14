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


async def scholarship_tolerance_days(
    session: AsyncSession, student_id: uuid.UUID, on: date
) -> int:
    """Max payment-tolerance window (días) among the student's active scholarships
    covering `on`. Beca charges get this as extra grace before a recargo (RF-T05)."""
    scholarships = (
        await session.exec(
            select(Scholarship).where(
                Scholarship.student_id == student_id,
                Scholarship.status == ScholarshipStatus.activa,
            )
        )
    ).all()
    best = 0
    for s in scholarships:
        if s.valid_from > on or (s.valid_to and s.valid_to < on):
            continue
        best = max(best, s.tolerance_days)
    return best


async def enforce_scholarship_tolerance(
    session: AsyncSession, institution: Institution, today: date | None = None
) -> int:
    """RF-T05: an active scholarship is suspended once the student leaves a
    beca charge unpaid past its due date + the scholarship tolerance window.
    Returns how many scholarships were suspended. Caller commits."""
    today = today or utcnow().date()
    scholarships = (
        await session.exec(
            select(Scholarship)
            .join(Student, Student.id == Scholarship.student_id)
            .where(
                Student.institution_id == institution.id,
                Scholarship.status == ScholarshipStatus.activa,
            )
        )
    ).all()
    suspended = 0
    for s in scholarships:
        charges = (
            await session.exec(
                select(Charge).where(
                    Charge.student_id == s.student_id,
                    Charge.scholarship_discount > 0,
                    Charge.due_date < today - timedelta(days=s.tolerance_days),
                    Charge.status.in_([ChargeStatus.pendiente, ChargeStatus.parcial]),  # type: ignore[attr-defined]
                )
            )
        ).all()
        overdue_unpaid = False
        for c in charges:
            if _net(c) - await charge_paid_amount(session, c.id) > 0:
                overdue_unpaid = True
                break
        if overdue_unpaid:
            s.status = ScholarshipStatus.suspendida
            session.add(s)
            suspended += 1
    return suspended


async def apply_late_fees(
    session: AsyncSession, institution: Institution, created_by: uuid.UUID, today: date | None = None
) -> int:
    """RF-T06: creates a recargo charge for each overdue charge without one.
    Beca charges still inside the scholarship tolerance window are skipped.
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
        # Beca charge still within its scholarship tolerance → no recargo yet.
        if charge.scholarship_discount > 0:
            tol = await scholarship_tolerance_days(session, charge.student_id, charge.due_date)
            if (today - charge.due_date).days <= tol:
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


async def scholarship_metrics(session: AsyncSession, today: date | None = None) -> dict:
    """RF-T reports: #/‰ becados and beca aplicada acumulada al día (mes/cuatrimestre)."""
    today = today or utcnow().date()
    active_students = (
        await session.exec(
            select(func.count()).select_from(Student).where(Student.status == "activo")
        )
    ).one()
    with_scholarship = (
        await session.exec(
            select(func.count(func.distinct(Scholarship.student_id))).where(
                Scholarship.status == ScholarshipStatus.activa
            )
        )
    ).one()

    async def _beca_sum(since: date) -> float:
        total = (
            await session.exec(
                select(func.coalesce(func.sum(Charge.scholarship_discount), 0.0)).where(
                    Charge.status != ChargeStatus.cancelado,
                    Charge.due_date >= since,
                    Charge.due_date <= today,
                )
            )
        ).one()
        return round(float(total), 2)

    from app.models import Term  # local import to avoid cycle at module load

    open_term = (
        await session.exec(select(Term).where(Term.is_open == True))  # noqa: E712
    ).first()
    term_start = open_term.start_date if open_term else today.replace(day=1)
    return {
        "active_students": int(active_students),
        "students_with_scholarship": int(with_scholarship),
        "pct_with_scholarship": round(100 * int(with_scholarship) / int(active_students), 1)
        if active_students
        else 0.0,
        "beca_mes": await _beca_sum(today.replace(day=1)),
        "beca_cuatrimestre": await _beca_sum(term_start),
    }
