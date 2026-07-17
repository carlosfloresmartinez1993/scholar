"""Treasury module (internal control, no payment gateway): charge concepts
(RF-T01), per-student payment schedule (RF-T02), manual payment capture with
receipt folios (RF-T03/T09), scholarships (RF-T05), late fees (RF-T06) and the
debt flag used to block official documents (RF-T07)."""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.common import utcnow
from app.models.catalog import Modality


class ChargeConceptKind(str, Enum):
    inscripcion = "inscripcion"
    reinscripcion = "reinscripcion"
    colegiatura = "colegiatura"
    titulacion = "titulacion"
    constancia = "constancia"
    recargo = "recargo"
    otro = "otro"


class ChargeConceptBase(SQLModel):
    name: str = Field(max_length=255)
    kind: ChargeConceptKind
    amount: float = Field(ge=0)
    program_id: uuid.UUID | None = None  # None = applies to all programs
    modality: Modality | None = None  # None = all modalities
    is_active: bool = True


class ChargeConcept(ChargeConceptBase, table=True):
    __tablename__ = "charge_concepts"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class ChargeConceptCreate(ChargeConceptBase):
    pass


class ChargeConceptPublic(ChargeConceptBase):
    id: uuid.UUID


class ChargeStatus(str, Enum):
    pendiente = "pendiente"
    parcial = "parcial"
    pagado = "pagado"
    cancelado = "cancelado"


class Charge(SQLModel, table=True):
    """One receivable on a student's account (a payment-plan installment,
    a one-off fee, or an auto-generated late fee)."""
    __tablename__ = "charges"
    # One auto-generated charge per (enrollment, concept, due date): a hard guard
    # against double-billing under concurrent generation. NULLs are distinct, so
    # manual/legacy charges (no enrollment) are unconstrained.
    __table_args__ = (
        UniqueConstraint(
            "group_enrollment_id", "concept_id", "due_date",
            name="uq_charges_enrollment_slot",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    concept_id: uuid.UUID | None = Field(default=None, foreign_key="charge_concepts.id")
    description: str = Field(max_length=255)  # e.g. "Colegiatura septiembre 2026"
    amount: float = Field(ge=0)
    scholarship_discount: float = Field(default=0, ge=0)  # RF-T05, frozen at generation
    due_date: date = Field(index=True)
    status: ChargeStatus = ChargeStatus.pendiente
    is_late_fee: bool = False
    source_charge_id: uuid.UUID | None = Field(default=None, foreign_key="charges.id")
    # Auto-billing (RF-T02): ties a charge to the term/enrollment it was generated
    # for, so a repeated cuatrimestre gets its own fresh charges. Nullable: manual
    # and legacy charges have neither.
    term_id: uuid.UUID | None = Field(default=None, foreign_key="terms.id", index=True)
    group_enrollment_id: uuid.UUID | None = Field(
        default=None, foreign_key="group_enrollments.id", index=True
    )
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class ChargeCreate(SQLModel):
    student_id: uuid.UUID
    concept_id: uuid.UUID | None = None
    description: str
    amount: float = Field(ge=0)
    due_date: date


class ChargePublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    concept_id: uuid.UUID | None
    description: str
    amount: float
    scholarship_discount: float
    due_date: date
    status: ChargeStatus
    is_late_fee: bool
    paid_amount: float = 0
    balance: float = 0


class PaymentPlanGenerateIn(SQLModel):
    """RF-T02: generate N installments of a concept for a student."""
    student_id: uuid.UUID
    concept_id: uuid.UUID
    installments: int = Field(ge=1, le=48)
    first_due_date: date
    day_interval: int | None = None  # None = monthly (same day each month)


class PaymentMethod(str, Enum):
    efectivo = "efectivo"
    transferencia = "transferencia"
    deposito = "deposito"
    tarjeta = "tarjeta"


class Payment(SQLModel, table=True):
    """RF-T03/T09: manual payment capture with sequential receipt folio."""
    __tablename__ = "payments"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    charge_id: uuid.UUID | None = Field(default=None, foreign_key="charges.id", index=True)
    amount: float = Field(gt=0)
    method: PaymentMethod
    bank_reference: str = Field(default="", max_length=128)
    receipt_folio: str = Field(unique=True, max_length=32)
    notes: str = Field(default="", max_length=512)
    received_by: uuid.UUID = Field(foreign_key="users.id")
    received_at: datetime = Field(default_factory=utcnow)
    cancelled: bool = False
    cancel_reason: str = Field(default="", max_length=255)


class PaymentAllocation(SQLModel, table=True):
    """Split of one payment across several charges, so a student who owes
    N colegiaturas settles them in a single cobro: one payment, one folio,
    one receipt (RF-T03)."""
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "charge_id", name="uq_payment_allocation"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(foreign_key="payments.id", index=True)
    charge_id: uuid.UUID = Field(foreign_key="charges.id", index=True)
    amount: float = Field(gt=0)


class PaymentAllocationPublic(SQLModel):
    charge_id: uuid.UUID
    amount: float


class PaymentCreate(SQLModel):
    student_id: uuid.UUID
    charge_id: uuid.UUID | None = None
    # Multi-charge cobro: the payment is allocated across these charges
    # oldest-due-first. Mutually exclusive with charge_id.
    charge_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    amount: float = Field(gt=0)
    method: PaymentMethod
    bank_reference: str = ""
    notes: str = ""


class PaymentPublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    charge_id: uuid.UUID | None
    amount: float
    method: PaymentMethod
    bank_reference: str
    receipt_folio: str
    notes: str
    received_at: datetime
    cancelled: bool
    allocations: list[PaymentAllocationPublic] = []


class ScholarshipStatus(str, Enum):
    solicitada = "solicitada"  # captured by treasury, awaiting admin authorization
    activa = "activa"          # authorized; discounts apply
    suspendida = "suspendida"  # lost for not paying within tolerance (RF-T05 tolerance)
    vencida = "vencida"        # past valid_to
    cancelada = "cancelada"    # rejected or revoked


class ScholarshipBase(SQLModel):
    name: str = Field(max_length=255)  # motivo / convenio
    pct: float | None = Field(default=None, ge=0, le=100)  # either pct
    fixed_amount: float | None = Field(default=None, ge=0)  # or fixed amount per charge
    valid_from: date
    valid_to: date | None = None
    # Días de tolerancia tras el vencimiento del cargo con beca: si el alumno no
    # paga dentro de la ventana pierde la beca y no se le genera recargo mientras
    # esté dentro de ella.
    tolerance_days: int = Field(default=0, ge=0)


class Scholarship(ScholarshipBase, table=True):
    """RF-T05: applies to colegiatura charges generated while valid. A new
    scholarship is created as `solicitada` and only starts discounting once an
    admin authorizes it (approved_by/authorized_at set)."""
    __tablename__ = "scholarships"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    status: ScholarshipStatus = ScholarshipStatus.solicitada
    requested_by: uuid.UUID = Field(foreign_key="users.id")
    approved_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    authorized_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ScholarshipCreate(ScholarshipBase):
    student_id: uuid.UUID


class ScholarshipPublic(ScholarshipBase):
    id: uuid.UUID
    student_id: uuid.UUID
    status: ScholarshipStatus
    approved_by: uuid.UUID | None = None


# --- Fiscal data for invoicing (Caja → Facturar) --------------------------------------

class FiscalProfileBase(SQLModel):
    rfc: str = Field(max_length=13)
    razon_social: str = Field(max_length=255)
    regimen_fiscal: str = Field(default="", max_length=8)   # clave SAT c_RegimenFiscal
    uso_cfdi: str = Field(default="G03", max_length=8)      # clave SAT c_UsoCFDI
    email: str = Field(default="", max_length=255)
    cp: str = Field(default="", max_length=5)               # código postal fiscal
    calle: str = Field(default="", max_length=255)
    no_ext: str = Field(default="", max_length=32)
    no_int: str = Field(default="", max_length=32)
    colonia: str = Field(default="", max_length=255)
    municipio: str = Field(default="", max_length=255)
    estado: str = Field(default="", max_length=255)
    pais: str = Field(default="México", max_length=64)


class StudentFiscalProfile(FiscalProfileBase, table=True):
    """Datos fiscales del alumno/receptor para facturación (RF-T)."""
    __tablename__ = "student_fiscal_profiles"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", unique=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class FiscalProfilePublic(FiscalProfileBase):
    id: uuid.UUID
    student_id: uuid.UUID


class AccountStatement(SQLModel):
    """RF-T04: online statement — charges, payments, balance, next due."""
    student_id: uuid.UUID
    charges: list[ChargePublic]
    payments: list[PaymentPublic]
    total_charged: float
    total_paid: float
    balance: float
    overdue_balance: float
    next_due_date: date | None
