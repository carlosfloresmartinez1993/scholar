"""Treasury business rules: balances and statements (RF-T04), scholarship
application (RF-T05), late fees (RF-T06), debt blocking (RF-T07) and payment
allocation (RF-T03)."""
import uuid
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Charge,
    ChargeConcept,
    ChargeConceptKind,
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
    session: AsyncSession,
    student_id: uuid.UUID,
    amount: float,
    on: date,
    kind: ChargeConceptKind | None = None,
) -> float:
    """RF-T05: best active scholarship applied to one charge amount. Becas apply
    to colegiatura only — anything else (inscripción, a charge with no concept)
    gets none."""
    if kind != ChargeConceptKind.colegiatura:
        return 0.0
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


# --- Auto-billing (RF-T02): charges generated from a group enrollment ----------

def _month_firsts(start: date, end: date) -> list[date]:
    """1st of every month the [start, end] span touches. A SEP–DIC term → the 1st
    of Sep, Oct, Nov, Dec. ponytail: due dates land on the 1st even if the term
    starts mid-month (the first colegiatura is then simply due at enrollment)."""
    firsts: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        firsts.append(date(year, month, 1))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return firsts


_SPANISH_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


async def resolve_concept(
    session: AsyncSession, kind: ChargeConceptKind, program_id, modality,
    institution_id: uuid.UUID,
) -> ChargeConcept | None:
    """Most-specific active price in the institution's tabulador: a row scoped to
    this program+modality beats a program-only row, beats a modality-only row,
    beats a global row. A row scoped to a *different* program or modality never
    matches."""
    concepts = (
        await session.exec(
            select(ChargeConcept).where(
                ChargeConcept.kind == kind,
                ChargeConcept.is_active == True,  # noqa: E712
                ChargeConcept.institution_id == institution_id,
            )
        )
    ).all()
    best, best_score = None, -1
    for c in concepts:
        if c.program_id is not None and c.program_id != program_id:
            continue
        if c.modality is not None and c.modality != modality:
            continue
        score = (2 if c.program_id is not None else 0) + (1 if c.modality is not None else 0)
        if score > best_score:
            best, best_score = c, score
    return best


async def generate_enrollment_charges(
    session: AsyncSession, *, student: Student, group, enrollment, kind,
    created_by: uuid.UUID, waive_enrollment_fee: bool = False,
) -> list[Charge]:
    """Auto-bill a group enrollment (RF-T02): the enrollment fee
    (inscripción/reinscripción, unless waived) + one colegiatura per month the
    term spans, due the 1st. Idempotent per enrollment. Best-effort — if the
    tabulador has no matching price the charge is skipped so enrollment is never
    blocked (a strict cohort run resolves prices up front). The scholarship pct is
    frozen onto colegiaturas only. Caller commits."""
    from app.models import GroupEnrollmentKind, PlanVersion, Rvoe, Term

    term = await session.get(Term, group.term_id)
    if term is None:
        return []
    plan = await session.get(PlanVersion, group.plan_version_id)
    rvoe = await session.get(Rvoe, plan.rvoe_id) if plan else None
    program_id = rvoe.program_id if rvoe else None
    modality = rvoe.modality if rvoe else None
    institution_id = student.institution_id

    # Per-slot idempotency: which (concept, due date) slots already exist for this
    # enrollment. Only missing slots are created — so a re-run (or a cohort backfill
    # after the tabulador is completed) fills gaps instead of skipping wholesale.
    existing = set(
        (
            await session.exec(
                select(Charge.concept_id, Charge.due_date).where(
                    Charge.group_enrollment_id == enrollment.id
                )
            )
        ).all()
    )

    created: list[Charge] = []
    if not waive_enrollment_fee:
        fee_kind = (
            ChargeConceptKind.inscripcion
            if kind == GroupEnrollmentKind.inscripcion
            else ChargeConceptKind.reinscripcion
        )
        fee = await resolve_concept(session, fee_kind, program_id, modality, institution_id)
        if fee is not None and (fee.id, term.start_date) not in existing:
            created.append(Charge(
                student_id=student.id, concept_id=fee.id,
                description=f"{fee.name} — {term.name}", amount=fee.amount,
                scholarship_discount=0.0,  # becas never apply to the enrollment fee
                due_date=term.start_date, term_id=term.id,
                group_enrollment_id=enrollment.id, created_by=created_by,
            ))

    colegiatura = await resolve_concept(
        session, ChargeConceptKind.colegiatura, program_id, modality, institution_id
    )
    if colegiatura is not None:
        for due in _month_firsts(term.start_date, term.end_date):
            if (colegiatura.id, due) in existing:
                continue
            discount = await active_scholarship_discount(
                session, student.id, colegiatura.amount, due,
                kind=ChargeConceptKind.colegiatura,
            )
            created.append(Charge(
                student_id=student.id, concept_id=colegiatura.id,
                description=f"{colegiatura.name} {_SPANISH_MONTHS[due.month - 1]} {due.year}",
                amount=colegiatura.amount, scholarship_discount=discount,
                due_date=due, term_id=term.id,
                group_enrollment_id=enrollment.id, created_by=created_by,
            ))

    if not created:
        return []
    # A concurrent run (e.g. two cohort clicks) can pass the slot check above and
    # race to insert the same slot. Flush inside a SAVEPOINT: if the unique
    # constraint fires, roll back just this attempt and report nothing billed —
    # the winner's charges stand, nothing is double-billed, the outer txn survives.
    try:
        async with session.begin_nested():
            session.add_all(created)
            await session.flush()
    except IntegrityError:
        return []
    return created


async def apply_scholarship_to_pending(
    session: AsyncSession, scholarship: Scholarship
) -> int:
    """When a beca is authorized after charges already exist, freeze its discount
    onto the student's still-open colegiatura charges (RF-T05). Returns how many
    charges changed. Caller commits."""
    charges = (
        await session.exec(
            select(Charge)
            .join(ChargeConcept, ChargeConcept.id == Charge.concept_id)
            .where(
                Charge.student_id == scholarship.student_id,
                ChargeConcept.kind == ChargeConceptKind.colegiatura,
                Charge.status.in_([ChargeStatus.pendiente, ChargeStatus.parcial]),  # type: ignore[attr-defined]
                Charge.due_date >= scholarship.valid_from,
            )
        )
    ).all()
    changed = 0
    for c in charges:
        discount = await active_scholarship_discount(
            session, c.student_id, c.amount, c.due_date, kind=ChargeConceptKind.colegiatura
        )
        if abs(discount - c.scholarship_discount) > 0.005:
            c.scholarship_discount = discount
            session.add(c)
            await refresh_charge_status(session, c)
            changed += 1
    return changed


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
