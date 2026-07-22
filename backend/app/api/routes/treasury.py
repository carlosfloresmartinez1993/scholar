"""Treasury: concepts (RF-T01), payment plans (RF-T02), manual payments with
receipt folio (RF-T03/T09), statements (RF-T04), scholarships (RF-T05), late
fees (RF-T06), collection reports (RF-T08) and accounting export (RF-T10)."""
import csv
import io
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import func, select

from app.api.deps import AnyStaff, Authorizer, SessionDep, TreasuryStaff
from app.api.routes.catalog import get_default_institution
from app.models import (
    AccountStatement,
    Charge,
    ChargeCondoneIn,
    ChargeConcept,
    ChargeConceptCreate,
    ChargeConceptKind,
    ChargeConceptPublic,
    ChargeConceptUpdate,
    ChargeCreate,
    ChargePublic,
    ChargeStatus,
    FiscalProfileBase,
    FiscalProfilePublic,
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    PlanVersion,
    Program,
    Rvoe,
    Payment,
    PaymentAllocation,
    PaymentAllocationPublic,
    PaymentCreate,
    PaymentPlanGenerateIn,
    PaymentPublic,
    Scholarship,
    ScholarshipCreate,
    ScholarshipPublic,
    ScholarshipStatus,
    Student,
    StudentFiscalProfile,
)
from app.models.common import utcnow
from app.services import audit
from app.services.folios import next_folio
from app.models.user import UserRole
from app.services.treasury import (
    active_scholarship_discount,
    apply_late_fees,
    apply_scholarship_to_pending,
    build_account_statement,
    charge_net,
    charge_paid_amount,
    charges_paid_map,
    generate_enrollment_charges,
    overdue_balance,
    refresh_charge_status,
    resolve_concept,
    scholarship_metrics,
    student_charges_public,
    term_billing_summary,
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


@router.patch("/concepts/{concept_id}")
async def update_concept(
    session: SessionDep, current_user: TreasuryStaff, concept_id: uuid.UUID,
    body: ChargeConceptUpdate,
) -> ChargeConceptPublic:
    """Edit a concept in place (e.g. yearly price bump). Existing charges froze
    their amount at generation, so past debts never move — only future charges
    use the new price. No more cloning concepts per cycle."""
    concept = await session.get(ChargeConcept, concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail="Concepto no encontrado")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("program_id") is not None:
        if await session.get(Program, changes["program_id"]) is None:
            raise HTTPException(status_code=404, detail="Programa no encontrado")
    for k, v in changes.items():
        setattr(concept, k, v)
    session.add(concept)
    audit.record(session, actor=current_user.email, action="charge_concept.updated",
                 entity="charge_concept", entity_id=str(concept.id),
                 detail=f"{concept.name} {changes}")
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
    concept = await session.get(ChargeConcept, body.concept_id) if body.concept_id else None
    if body.concept_id and (
        concept is None
        or not concept.is_active
        or concept.institution_id != student.institution_id
    ):
        raise HTTPException(status_code=404, detail="Concepto no encontrado")
    discount = await active_scholarship_discount(
        session, student.id, body.amount, body.due_date,
        kind=concept.kind if concept else None, concept_id=body.concept_id,
    )
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
        discount = await active_scholarship_discount(
            session, student.id, concept.amount, due,
            kind=concept.kind, concept_id=concept.id,
        )
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


@router.post("/groups/{group_id}/generate-charges")
async def generate_group_charges(
    session: SessionDep, current_user: TreasuryStaff, group_id: uuid.UUID,
    waive_enrollment_fee: bool = False,
) -> dict:
    """Cohort billing (Servo's AsignaciónCobranza): bill every active enrollment in
    a group that isn't billed yet — inscripción/reinscripción + monthly colegiaturas.
    Idempotent. Fails if the group's program has no colegiatura price in the tabulador."""
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    institution = await get_default_institution(session)
    plan = await session.get(PlanVersion, group.plan_version_id)
    rvoe = await session.get(Rvoe, plan.rvoe_id) if plan else None
    program_id = rvoe.program_id if rvoe else None
    modality = rvoe.modality if rvoe else None
    if await resolve_concept(
        session, ChargeConceptKind.colegiatura, program_id, modality, institution.id
    ) is None:
        raise HTTPException(
            status_code=409,
            detail="Configura el concepto de colegiatura (tabulador) de este programa/modalidad",
        )
    enrollments = (
        await session.exec(
            select(GroupEnrollment).where(
                GroupEnrollment.group_id == group_id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
            )
        )
    ).all()
    students_billed = 0
    charges_created = 0
    for en in enrollments:
        student = await session.get(Student, en.student_id)
        if student is None:
            continue
        created = await generate_enrollment_charges(
            session, student=student, group=group, enrollment=en, kind=en.kind,
            created_by=current_user.id, waive_enrollment_fee=waive_enrollment_fee,
        )
        if created:
            students_billed += 1
            charges_created += len(created)
    audit.record(session, actor=current_user.email, action="group_charges.generated",
                 entity="group", entity_id=str(group_id),
                 detail=f"{students_billed} alumnos, {charges_created} cargos")
    await session.commit()
    return {"students_billed": students_billed, "charges_created": charges_created}


@router.get("/groups/{group_id}/billing-status")
async def group_billing_status(
    session: SessionDep, _: TreasuryStaff, group_id: uuid.UUID
) -> list[dict]:
    """Roster of a group's active enrollments with whether each has been billed —
    so staff see who's missing charges and can back-bill the gaps."""
    if await session.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    enrollments = (
        await session.exec(
            select(GroupEnrollment, Student)
            .join(Student, Student.id == GroupEnrollment.student_id)
            .where(
                GroupEnrollment.group_id == group_id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
            )
            .order_by(Student.full_name)
        )
    ).all()
    enrollment_ids = [en.id for en, _ in enrollments]
    counts: dict = {}
    if enrollment_ids:
        counts = dict(
            (
                await session.exec(
                    select(Charge.group_enrollment_id, func.count(Charge.id))
                    .where(Charge.group_enrollment_id.in_(enrollment_ids))  # type: ignore[attr-defined]
                    .group_by(Charge.group_enrollment_id)
                )
            ).all()
        )
    return [
        {
            "student_id": str(student.id),
            "student_name": student.full_name,
            "enrollment_number": student.enrollment_number,
            "charges_count": int(counts.get(en.id, 0)),
            "billed": counts.get(en.id, 0) > 0,
        }
        for en, student in enrollments
    ]


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


@router.post("/charges/{charge_id}/condone")
async def condone_charge(
    session: SessionDep, current_user: TreasuryStaff, charge_id: uuid.UUID,
    body: ChargeCondoneIn,
) -> ChargePublic:
    """Condonación: forgive part or all of a charge's open balance at caja,
    leaving the paid history intact (unlike cancelling the charge)."""
    # Row lock: two concurrent condonations must accumulate, not lose an update.
    charge = (
        await session.exec(
            select(Charge).where(Charge.id == charge_id).with_for_update()
        )
    ).first()
    if charge is None:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    if charge.status in (ChargeStatus.cancelado, ChargeStatus.pagado):
        raise HTTPException(status_code=409, detail="El cargo no tiene saldo por condonar")
    paid = await charge_paid_amount(session, charge_id)
    open_balance = round(charge_net(charge) - paid, 2)
    if open_balance <= 0:
        raise HTTPException(status_code=409, detail="El cargo no tiene saldo por condonar")
    amount = round(body.amount if body.amount is not None else open_balance, 2)
    if amount > open_balance:
        raise HTTPException(
            status_code=400,
            detail=f"La condonación excede el saldo del cargo ({open_balance:.2f})",
        )
    charge.condoned_amount = round(charge.condoned_amount + amount, 2)
    charge.condoned_reason = body.reason
    await refresh_charge_status(session, charge)
    audit.record(session, actor=current_user.email, action="charge.condoned",
                 entity="charge", entity_id=str(charge_id),
                 detail=f"${amount:.2f} — {body.reason}")
    await session.commit()
    await session.refresh(charge)
    return ChargePublic(
        id=charge.id, student_id=charge.student_id, concept_id=charge.concept_id,
        description=charge.description, amount=charge.amount,
        scholarship_discount=charge.scholarship_discount,
        condoned_amount=charge.condoned_amount, due_date=charge.due_date,
        status=charge.status, is_late_fee=charge.is_late_fee, paid_amount=paid,
        balance=max(charge_net(charge) - paid, 0.0),
    )


# --- Payments (RF-T03/T09) --------------------------------------------------------------

@router.post("/payments", status_code=201)
async def register_payment(
    session: SessionDep, current_user: TreasuryStaff, body: PaymentCreate
) -> PaymentPublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if body.charge_id and body.charge_ids:
        raise HTTPException(
            status_code=400, detail="Use charge_id o charge_ids, no ambos"
        )
    charge = None
    targets: list[Charge] = []
    if body.charge_ids:
        ids = list(dict.fromkeys(body.charge_ids))  # dedupe, keep order
        # Lock every selected charge (deterministic order → no deadlock) before
        # reading balances, so two concurrent multi-cobros can't both allocate
        # against the same charge and overstate the paid total.
        locked = (
            await session.exec(
                select(Charge).where(Charge.id.in_(ids)).with_for_update().order_by(Charge.id)  # type: ignore[attr-defined]
            )
        ).all()
        by_id = {c.id: c for c in locked}
        for charge_id in ids:
            c = by_id.get(charge_id)
            if c is None or c.student_id != student.id:
                raise HTTPException(status_code=400, detail="Cargo inválido")
            if c.status == ChargeStatus.cancelado:
                raise HTTPException(
                    status_code=409, detail=f"El cargo '{c.description}' está cancelado"
                )
            targets.append(c)
        targets.sort(key=lambda c: (c.due_date, c.created_at))
    elif body.charge_id:
        charge = await session.get(Charge, body.charge_id)
        if charge is None or charge.student_id != student.id:
            raise HTTPException(status_code=400, detail="Cargo inválido")
        if charge.status == ChargeStatus.cancelado:
            raise HTTPException(status_code=409, detail="El cargo está cancelado")
    institution = await get_default_institution(session)
    folio = await next_folio(session, institution.id, "recibo")
    payment = Payment(
        **body.model_dump(exclude={"charge_ids"}),
        receipt_folio=folio,
        received_by=current_user.id,
    )
    session.add(payment)
    await session.flush()
    allocations: list[PaymentAllocation] = []
    if targets:
        # Split the payment oldest-due-first, capped at each charge's open
        # balance; any remainder stays as saldo a favor on the payment itself.
        paid_map = await charges_paid_map(session, [c.id for c in targets])
        remaining = round(body.amount, 2)
        new_totals: dict[uuid.UUID, float] = {}
        for c in targets:
            if remaining <= 0:
                break
            net = charge_net(c)
            balance = round(net - paid_map.get(c.id, 0.0), 2)
            if balance <= 0:
                continue
            take = min(balance, remaining)
            allocations.append(
                PaymentAllocation(payment_id=payment.id, charge_id=c.id, amount=take)
            )
            new_totals[c.id] = paid_map.get(c.id, 0.0) + take
            remaining = round(remaining - take, 2)
        if not allocations:
            raise HTTPException(
                status_code=409, detail="Los cargos seleccionados no tienen saldo"
            )
        session.add_all(allocations)
        # Derive each touched charge's status from the in-memory paid total
        # (mirrors refresh_charge_status) instead of re-querying per charge.
        for c in targets:
            paid = new_totals.get(c.id)
            if paid is None:
                continue
            net = charge_net(c)
            c.status = (
                ChargeStatus.pagado
                if paid >= net - 0.005
                else ChargeStatus.parcial
                if paid > 0
                else ChargeStatus.pendiente
            )
            session.add(c)
        await session.flush()
    if charge:
        await refresh_charge_status(session, charge)
    audit.record(session, actor=current_user.email, action="payment.registered",
                 entity="payment", entity_id=folio,
                 detail=f"${body.amount} {body.method}")
    await session.commit()
    await session.refresh(payment)
    pub = PaymentPublic.model_validate(payment, from_attributes=True)
    pub.allocations = [
        PaymentAllocationPublic(charge_id=a.charge_id, amount=a.amount)
        for a in allocations
    ]
    return pub


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
    # A multi-charge payment reopens every charge it was allocated to.
    allocs = (
        await session.exec(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
        )
    ).all()
    for a in allocs:
        c = await session.get(Charge, a.charge_id)
        if c:
            await refresh_charge_status(session, c)
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
    return await build_account_statement(session, student_id)


# --- Scholarships (RF-T05) -----------------------------------------------------------------

@router.get("/scholarships")
async def list_scholarships(
    session: SessionDep, _: TreasuryStaff, student_id: uuid.UUID | None = None,
    status: ScholarshipStatus | None = None,
) -> list[ScholarshipPublic]:
    q = select(Scholarship).order_by(Scholarship.created_at.desc())  # type: ignore[attr-defined]
    if student_id:
        q = q.where(Scholarship.student_id == student_id)
    if status:
        q = q.where(Scholarship.status == status)
    return (await session.exec(q)).all()


@router.post("/scholarships", status_code=201)
async def create_scholarship(
    session: SessionDep, current_user: TreasuryStaff, body: ScholarshipCreate
) -> ScholarshipPublic:
    """RF-T05: creates a beca. Requested by treasury staff it stays `solicitada`
    (no discount) until an admin authorizes it; created by an admin/superuser it
    activates immediately."""
    if await session.get(Student, body.student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    # Becas are percentage-only now (frozen onto each charge at generation).
    if body.pct is None:
        raise HTTPException(status_code=400, detail="Indica el porcentaje de la beca")
    if not 0 < body.pct <= 100:
        raise HTTPException(
            status_code=400, detail="El porcentaje debe ser mayor a 0 y no exceder 100%"
        )
    if body.fixed_amount is not None:
        raise HTTPException(
            status_code=400, detail="Las becas son solo por porcentaje (sin monto fijo)"
        )
    if body.concept_id is not None:
        concept = await session.get(ChargeConcept, body.concept_id)
        if concept is None or not concept.is_active:
            raise HTTPException(status_code=404, detail="Concepto no encontrado")
    auto_approve = current_user.is_superuser or current_user.role in (
        UserRole.admin_sistema, UserRole.direccion
    )
    scholarship = Scholarship(
        **body.model_dump(), status=ScholarshipStatus.solicitada, requested_by=current_user.id
    )
    if auto_approve:
        scholarship.status = ScholarshipStatus.activa
        scholarship.approved_by = current_user.id
        scholarship.authorized_at = utcnow()
    session.add(scholarship)
    if auto_approve:
        await session.flush()
        updated = await apply_scholarship_to_pending(session, scholarship)
        audit.record(session, actor=current_user.email, action="scholarship.authorized",
                     entity="scholarship", entity_id=str(scholarship.id),
                     detail=f"{body.name} — alta directa, {updated} cargos actualizados")
    else:
        audit.record(session, actor=current_user.email, action="scholarship.requested",
                     entity="scholarship", entity_id=str(scholarship.id), detail=body.name)
    await session.commit()
    await session.refresh(scholarship)
    return scholarship


@router.post("/scholarships/{scholarship_id}/authorize")
async def authorize_scholarship(
    session: SessionDep, current_user: Authorizer, scholarship_id: uuid.UUID
) -> ScholarshipPublic:
    """Admin sign-off: a `solicitada` scholarship becomes `activa` and starts
    discounting future charges (RF-T05)."""
    scholarship = await session.get(Scholarship, scholarship_id)
    if scholarship is None:
        raise HTTPException(status_code=404, detail="Beca no encontrada")
    if scholarship.status != ScholarshipStatus.solicitada:
        raise HTTPException(status_code=409, detail="La beca no está en solicitud")
    scholarship.status = ScholarshipStatus.activa
    scholarship.approved_by = current_user.id
    scholarship.authorized_at = utcnow()
    session.add(scholarship)
    # Beca granted after the student was already billed → apply it retroactively
    # to their still-open colegiatura charges (RF-T05).
    updated = await apply_scholarship_to_pending(session, scholarship)
    audit.record(session, actor=current_user.email, action="scholarship.authorized",
                 entity="scholarship", entity_id=str(scholarship.id),
                 detail=f"{scholarship.name} — {updated} cargos actualizados")
    await session.commit()
    await session.refresh(scholarship)
    return scholarship


@router.post("/scholarships/{scholarship_id}/reject")
async def reject_scholarship(
    session: SessionDep, current_user: Authorizer, scholarship_id: uuid.UUID, reason: str = ""
) -> ScholarshipPublic:
    scholarship = await session.get(Scholarship, scholarship_id)
    if scholarship is None:
        raise HTTPException(status_code=404, detail="Beca no encontrada")
    if scholarship.status not in (ScholarshipStatus.solicitada, ScholarshipStatus.activa):
        raise HTTPException(status_code=409, detail="La beca no puede rechazarse")
    scholarship.status = ScholarshipStatus.cancelada
    session.add(scholarship)
    audit.record(session, actor=current_user.email, action="scholarship.rejected",
                 entity="scholarship", entity_id=str(scholarship.id), detail=reason)
    await session.commit()
    await session.refresh(scholarship)
    return scholarship


# --- Fiscal profile (Caja → Facturar) ----------------------------------------------------

@router.get("/students/{student_id}/fiscal")
async def get_fiscal_profile(
    session: SessionDep, _: TreasuryStaff, student_id: uuid.UUID
) -> FiscalProfilePublic | None:
    return (
        await session.exec(
            select(StudentFiscalProfile).where(StudentFiscalProfile.student_id == student_id)
        )
    ).first()


@router.put("/students/{student_id}/fiscal")
async def upsert_fiscal_profile(
    session: SessionDep, current_user: TreasuryStaff, student_id: uuid.UUID, body: FiscalProfileBase
) -> FiscalProfilePublic:
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    profile = (
        await session.exec(
            select(StudentFiscalProfile).where(StudentFiscalProfile.student_id == student_id)
        )
    ).first()
    if profile is None:
        profile = StudentFiscalProfile(student_id=student_id, **body.model_dump())
    else:
        for k, v in body.model_dump().items():
            setattr(profile, k, v)
        profile.updated_at = utcnow()
    session.add(profile)
    audit.record(session, actor=current_user.email, action="fiscal_profile.saved",
                 entity="student", entity_id=str(student_id), detail=body.rfc)
    await session.commit()
    await session.refresh(profile)
    return profile


# --- Late fees (RF-T06) -----------------------------------------------------------------------

@router.post("/late-fees/run")
async def run_late_fees(session: SessionDep, current_user: TreasuryStaff) -> dict:
    institution = await get_default_institution(session)
    # Becas are never auto-suspended — a scholarship is kept for the whole career
    # even if a colegiatura goes unpaid (policy). Late fees still accrue after the
    # scholarship tolerance window (handled inside apply_late_fees).
    created = await apply_late_fees(session, institution, current_user.id)
    audit.record(session, actor=current_user.email, action="late_fees.applied",
                 entity="institution", entity_id=str(institution.id),
                 detail=f"recargos={created}")
    await session.commit()
    return {"created": created}


@router.get("/reports/scholarships")
async def scholarship_report(session: SessionDep, _: TreasuryStaff) -> dict:
    """RF-T reports: becados, % becados y beca aplicada acumulada al día."""
    return await scholarship_metrics(session)


@router.get("/reports/term-summary")
async def term_summary_report(session: SessionDep, _: TreasuryStaff) -> list[dict]:
    """RF-T08: expected vs collected per cuatrimestre, with the concept split."""
    return await term_billing_summary(session)


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
        balance = max(charge_net(charge) - paid, 0.0)
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
