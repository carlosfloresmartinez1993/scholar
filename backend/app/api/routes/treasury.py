"""Treasury: concepts (RF-T01), payment plans (RF-T02), manual payments with
receipt folio (RF-T03/T09), statements (RF-T04), scholarships (RF-T05), late
fees (RF-T06), collection reports (RF-T08) and accounting export (RF-T10)."""
import csv
import io
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.api.deps import AnyStaff, SessionDep, TreasuryStaff
from app.api.routes.catalog import get_default_institution
from app.models import (
    AccountStatement,
    Charge,
    ChargeConcept,
    ChargeConceptCreate,
    ChargeConceptPublic,
    ChargeCreate,
    ChargePublic,
    ChargeStatus,
    Payment,
    PaymentCreate,
    PaymentPlanGenerateIn,
    PaymentPublic,
    Scholarship,
    ScholarshipCreate,
    ScholarshipPublic,
    Student,
)
from app.models.common import utcnow
from app.services import audit
from app.services.folios import next_folio
from app.services.treasury import (
    active_scholarship_discount,
    apply_late_fees,
    charge_paid_amount,
    overdue_balance,
    refresh_charge_status,
    student_charges_public,
)

router = APIRouter(prefix="/treasury", tags=["treasury"])


# --- Concepts (RF-T01) ------------------------------------------------------------

@router.get("/concepts")
async def list_concepts(session: SessionDep, _: AnyStaff) -> list[ChargeConceptPublic]:
    return (await session.exec(select(ChargeConcept).order_by(ChargeConcept.name))).all()


@router.post("/concepts", status_code=201)
async def create_concept(
    session: SessionDep, current_user: TreasuryStaff, body: ChargeConceptCreate
) -> ChargeConceptPublic:
    institution = await get_default_institution(session)
    concept = ChargeConcept(**body.model_dump(), institution_id=institution.id)
    session.add(concept)
    audit.record(session, actor=current_user.email, action="charge_concept.created",
                 entity="charge_concept", entity_id=str(concept.id), detail=concept.name)
    await session.commit()
    await session.refresh(concept)
    return concept


# --- Charges & payment plans (RF-T02) ------------------------------------------------

@router.post("/charges", status_code=201)
async def create_charge(
    session: SessionDep, current_user: TreasuryStaff, body: ChargeCreate
) -> ChargePublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    discount = await active_scholarship_discount(session, student.id, body.amount, body.due_date)
    charge = Charge(
        **body.model_dump(), scholarship_discount=discount, created_by=current_user.id
    )
    session.add(charge)
    audit.record(session, actor=current_user.email, action="charge.created",
                 entity="charge", entity_id=str(charge.id),
                 detail=f"{charge.description} ${charge.amount}")
    await session.commit()
    await session.refresh(charge)
    return ChargePublic(
        id=charge.id, student_id=charge.student_id, concept_id=charge.concept_id,
        description=charge.description, amount=charge.amount,
        scholarship_discount=charge.scholarship_discount, due_date=charge.due_date,
        status=charge.status, is_late_fee=charge.is_late_fee, paid_amount=0.0,
        balance=max(charge.amount - charge.scholarship_discount, 0.0),
    )


@router.post("/payment-plans", status_code=201)
async def generate_payment_plan(
    session: SessionDep, current_user: TreasuryStaff, body: PaymentPlanGenerateIn
) -> list[ChargePublic]:
    """RF-T02: N installments of a concept; scholarships applied per charge (RF-T05)."""
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    concept = await session.get(ChargeConcept, body.concept_id)
    if concept is None or not concept.is_active:
        raise HTTPException(status_code=404, detail="Concepto no encontrado")
    created_ids = []
    for i in range(body.installments):
        if body.day_interval:
            due = body.first_due_date + timedelta(days=body.day_interval * i)
        else:  # monthly, same day
            month_index = body.first_due_date.month - 1 + i
            year = body.first_due_date.year + month_index // 12
            month = month_index % 12 + 1
            day = min(body.first_due_date.day, 28)
            due = date(year, month, day)
        discount = await active_scholarship_discount(session, student.id, concept.amount, due)
        charge = Charge(
            student_id=student.id,
            concept_id=concept.id,
            description=f"{concept.name} {i + 1}/{body.installments}",
            amount=concept.amount,
            scholarship_discount=discount,
            due_date=due,
            created_by=current_user.id,
        )
        session.add(charge)
        await session.flush()
        created_ids.append(charge.id)
    audit.record(session, actor=current_user.email, action="payment_plan.generated",
                 entity="student", entity_id=str(student.id),
                 detail=f"{concept.name} x{body.installments}")
    await session.commit()
    charges = await student_charges_public(session, student.id)
    return [c for c in charges if c.id in set(created_ids)]


@router.post("/charges/{charge_id}/cancel")
async def cancel_charge(
    session: SessionDep, current_user: TreasuryStaff, charge_id: uuid.UUID, reason: str = ""
) -> dict:
    charge = await session.get(Charge, charge_id)
    if charge is None:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    if await charge_paid_amount(session, charge_id) > 0:
        raise HTTPException(status_code=409, detail="El cargo ya tiene pagos aplicados")
    late_fees = (
        await session.exec(
            select(Charge).where(
                Charge.source_charge_id == charge_id,
                Charge.status != ChargeStatus.cancelado,
            )
        )
    ).all()
    for fee in late_fees:
        if await charge_paid_amount(session, fee.id) > 0:
            raise HTTPException(status_code=409, detail="El recargo asociado ya tiene pagos aplicados")
    charge.status = ChargeStatus.cancelado
    session.add(charge)
    for fee in late_fees:
        fee.status = ChargeStatus.cancelado
        session.add(fee)
        audit.record(session, actor=current_user.email, action="charge.cancelled",
                     entity="charge", entity_id=str(fee.id),
                     detail=f"Recargo cancelado junto con el cargo origen. {reason}".strip())
    audit.record(session, actor=current_user.email, action="charge.cancelled",
                 entity="charge", entity_id=str(charge_id), detail=reason)
    await session.commit()
    return {"ok": True}


# --- Payments (RF-T03/T09) --------------------------------------------------------------

@router.post("/payments", status_code=201)
async def register_payment(
    session: SessionDep, current_user: TreasuryStaff, body: PaymentCreate
) -> PaymentPublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    charge = None
    if body.charge_id:
        charge = await session.get(Charge, body.charge_id)
        if charge is None or charge.student_id != student.id:
            raise HTTPException(status_code=400, detail="Cargo inválido")
        if charge.status == ChargeStatus.cancelado:
            raise HTTPException(status_code=409, detail="El cargo está cancelado")
    institution = await get_default_institution(session)
    folio = await next_folio(session, institution.id, "recibo")
    payment = Payment(
        **body.model_dump(), receipt_folio=folio, received_by=current_user.id
    )
    session.add(payment)
    await session.flush()
    if charge:
        await refresh_charge_status(session, charge)
    audit.record(session, actor=current_user.email, action="payment.registered",
                 entity="payment", entity_id=folio,
                 detail=f"${body.amount} {body.method}")
    await session.commit()
    await session.refresh(payment)
    return payment


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(
    session: SessionDep, current_user: TreasuryStaff, payment_id: uuid.UUID, reason: str
) -> PaymentPublic:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    payment.cancelled = True
    payment.cancel_reason = reason
    session.add(payment)
    if payment.charge_id:
        charge = await session.get(Charge, payment.charge_id)
        if charge:
            await refresh_charge_status(session, charge)
    audit.record(session, actor=current_user.email, action="payment.cancelled",
                 entity="payment", entity_id=payment.receipt_folio, detail=reason)  # RT-08
    await session.commit()
    await session.refresh(payment)
    return payment


@router.get("/students/{student_id}/statement")
async def account_statement(
    session: SessionDep, _: TreasuryStaff, student_id: uuid.UUID
) -> AccountStatement:
    """RF-T04: cargos, pagos, saldo y próximos vencimientos."""
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    charges = await student_charges_public(session, student_id)
    payments = (
        await session.exec(
            select(Payment).where(Payment.student_id == student_id).order_by(Payment.received_at)
        )
    ).all()
    active = [c for c in charges if c.status != ChargeStatus.cancelado]
    total_charged = round(sum(max(c.amount - c.scholarship_discount, 0) for c in active), 2)
    total_paid = round(sum(p.amount for p in payments if not p.cancelled), 2)
    pending = [c for c in active if c.balance > 0]
    today = utcnow().date()
    upcoming = [c.due_date for c in pending if c.due_date >= today]
    return AccountStatement(
        student_id=student_id,
        charges=charges,
        payments=[PaymentPublic.model_validate(p, from_attributes=True) for p in payments],
        total_charged=total_charged,
        total_paid=total_paid,
        balance=round(sum(c.balance for c in pending), 2),
        overdue_balance=await overdue_balance(session, student_id),
        next_due_date=min(upcoming) if upcoming else None,
    )


# --- Scholarships (RF-T05) -----------------------------------------------------------------

@router.get("/scholarships")
async def list_scholarships(
    session: SessionDep, _: TreasuryStaff, student_id: uuid.UUID | None = None
) -> list[ScholarshipPublic]:
    q = select(Scholarship)
    if student_id:
        q = q.where(Scholarship.student_id == student_id)
    return (await session.exec(q)).all()


@router.post("/scholarships", status_code=201)
async def create_scholarship(
    session: SessionDep, current_user: TreasuryStaff, body: ScholarshipCreate
) -> ScholarshipPublic:
    if await session.get(Student, body.student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if (body.pct is None) == (body.fixed_amount is None):
        raise HTTPException(status_code=400, detail="Indica porcentaje o monto fijo (solo uno)")
    scholarship = Scholarship(**body.model_dump(), approved_by=current_user.id)
    session.add(scholarship)
    audit.record(session, actor=current_user.email, action="scholarship.created",
                 entity="scholarship", entity_id=str(scholarship.id), detail=body.name)
    await session.commit()
    await session.refresh(scholarship)
    return scholarship


# --- Late fees (RF-T06) -----------------------------------------------------------------------

@router.post("/late-fees/run")
async def run_late_fees(session: SessionDep, current_user: TreasuryStaff) -> dict:
    institution = await get_default_institution(session)
    created = await apply_late_fees(session, institution, current_user.id)
    audit.record(session, actor=current_user.email, action="late_fees.applied",
                 entity="institution", entity_id=str(institution.id), detail=str(created))
    await session.commit()
    return {"created": created}


# --- Reports & export (RF-T08, RF-T10) ----------------------------------------------------------

@router.get("/reports/collection")
async def collection_report(
    session: SessionDep, _: TreasuryStaff, date_from: date, date_to: date
) -> dict:
    payments = (
        await session.exec(
            select(Payment).where(
                Payment.cancelled == False,  # noqa: E712
                Payment.received_at >= date_from,
                Payment.received_at < date_to + timedelta(days=1),
            )
        )
    ).all()
    by_method: dict[str, float] = {}
    for p in payments:
        by_method[p.method] = round(by_method.get(p.method, 0) + p.amount, 2)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "payments_count": len(payments),
        "total": round(sum(p.amount for p in payments), 2),
        "by_method": by_method,
    }


@router.get("/reports/aging")
async def aging_report(session: SessionDep, _: TreasuryStaff) -> list[dict]:
    """Cartera vencida por antigüedad (RF-T08)."""
    today = utcnow().date()
    charges = (
        await session.exec(
            select(Charge, Student)
            .join(Student, Student.id == Charge.student_id)
            .where(
                Charge.due_date < today,
                Charge.status.in_([ChargeStatus.pendiente, ChargeStatus.parcial]),  # type: ignore[attr-defined]
            )
            .order_by(Charge.due_date)
        )
    ).all()
    rows = []
    for charge, student in charges:
        paid = await charge_paid_amount(session, charge.id)
        balance = max(charge.amount - charge.scholarship_discount - paid, 0.0)
        if balance <= 0:
            continue
        days = (today - charge.due_date).days
        bucket = "1-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
        rows.append(
            {
                "student_id": str(student.id),
                "student_name": student.full_name,
                "enrollment_number": student.enrollment_number,
                "description": charge.description,
                "due_date": charge.due_date.isoformat(),
                "days_overdue": days,
                "bucket": bucket,
                "balance": round(balance, 2),
            }
        )
    return rows


@router.get("/exports/movements")
async def export_movements(
    session: SessionDep, _: TreasuryStaff, date_from: date, date_to: date
) -> StreamingResponse:
    """RF-T10: CSV compatible with common Mexican accounting systems."""
    payments = (
        await session.exec(
            select(Payment, Student)
            .join(Student, Student.id == Payment.student_id)
            .where(Payment.received_at >= date_from, Payment.received_at < date_to + timedelta(days=1))
            .order_by(Payment.received_at)
        )
    ).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Folio", "Fecha", "Matricula", "Alumno", "Monto", "Metodo",
                     "Referencia", "Cancelado", "Notas"])
    for payment, student in payments:
        writer.writerow(
            [payment.receipt_folio, payment.received_at.isoformat(), student.enrollment_number,
             student.full_name, f"{payment.amount:.2f}", payment.method,
             payment.bank_reference, "SI" if payment.cancelled else "NO", payment.notes]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="movimientos_{date_from}_{date_to}.csv"'},
    )
