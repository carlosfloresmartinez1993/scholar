"""Treasury module (internal control, no payment gateway): charge concepts
(RF-T01), per-student payment schedule (RF-T02), manual payment capture with
receipt folios (RF-T03/T09), scholarships (RF-T05), late fees (RF-T06) and the
debt flag used to block official documents (RF-T07)."""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel

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
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def net_amount(self) -> float:
        return max(self.amount - self.scholarship_discount, 0.0)


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


class PaymentCreate(SQLModel):
    student_id: uuid.UUID
    charge_id: uuid.UUID | None = None
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


class ScholarshipStatus(str, Enum):
    activa = "activa"
    vencida = "vencida"
    cancelada = "cancelada"


class ScholarshipBase(SQLModel):
    name: str = Field(max_length=255)  # motivo / convenio
    pct: float | None = Field(default=None, ge=0, le=100)  # either pct
    fixed_amount: float | None = Field(default=None, ge=0)  # or fixed amount per charge
    valid_from: date
    valid_to: date | None = None


class Scholarship(ScholarshipBase, table=True):
    """RF-T05: applies to colegiatura charges generated while valid."""
    __tablename__ = "scholarships"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="students.id", index=True)
    status: ScholarshipStatus = ScholarshipStatus.activa
    approved_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class ScholarshipCreate(ScholarshipBase):
    student_id: uuid.UUID


class ScholarshipPublic(ScholarshipBase):
    id: uuid.UUID
    student_id: uuid.UUID
    status: ScholarshipStatus


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
