"""Idempotent DEMO seed for localhost: fills the institution's fiscal header,
creates one student with fiscal data, a paid colegiatura (so there is a payment
to *Facturar* in Caja) and a pending one (to test *Cobrar*).

Run with the stack up:  docker compose exec backend python -m app.demo_data
Safe to re-run — it keys off the demo CURP and won't duplicate.
"""
import asyncio
import logging
from datetime import date, timedelta

from sqlmodel import select

from app.core.db import async_session_factory
from app.models import (
    Campus,
    Charge,
    Institution,
    Payment,
    Student,
    StudentFiscalProfile,
    User,
)
from app.services.folios import next_folio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEMO_CURP = "PAEE900101HBCRLM09"
TODAY = date.today()


async def main() -> None:
    async with async_session_factory() as session:
        institution = (await session.exec(select(Institution))).first()
        if institution is None:
            raise SystemExit("Run `python -m app.initial_data` first.")
        campus = (
            await session.exec(select(Campus).where(Campus.institution_id == institution.id))
        ).first()
        admin = (await session.exec(select(User))).first()

        # 1) Institution fiscal header (used at the top of every receipt).
        institution.rfc = "IEE070919PCA"
        institution.fiscal_address = (
            "CALLE OCTAVA 1389\n"
            "OBRERA\n"
            "ENSENADA, ENSENADA, BAJA CALIFORNIA C.P. 22830"
        )
        session.add(institution)

        # 2) Demo student (idempotent by CURP).
        student = (
            await session.exec(select(Student).where(Student.curp == DEMO_CURP))
        ).first()
        if student is None:
            student = Student(
                institution_id=institution.id,
                campus_id=campus.id,
                curp=DEMO_CURP,
                full_name="PAEZ ESNAYRA EMILIO",
                email="emilio.paez@demo.mx",
                phone="6461234567",
                enrollment_number="62626011",
            )
            session.add(student)
            await session.flush()
            logger.info("demo student created: %s", student.enrollment_number)

            # Fiscal profile (receptor de la factura).
            session.add(
                StudentFiscalProfile(
                    student_id=student.id,
                    rfc="PAEE900101AB3",
                    razon_social="EMILIO PAEZ ESNAYRA",
                    regimen_fiscal="612",
                    uso_cfdi="G03",
                    email="emilio.paez@demo.mx",
                    cp="22830",
                    calle="Av. Reforma",
                    no_ext="123",
                    colonia="Centro",
                    municipio="Ensenada",
                    estado="Baja California",
                )
            )

            # Paid colegiatura → gives us a payment to Facturar.
            paid = Charge(
                student_id=student.id,
                description="COLEGIATURA JULIO",
                amount=3410,
                due_date=TODAY - timedelta(days=5),
                created_by=admin.id,
            )
            session.add(paid)
            await session.flush()
            folio = await next_folio(session, institution.id, "recibo")
            session.add(
                Payment(
                    student_id=student.id,
                    charge_id=paid.id,
                    amount=3410,
                    method="transferencia",
                    bank_reference="6258120",
                    receipt_folio=folio,
                    notes="09/07 5985 ref 6258120",
                    received_by=admin.id,
                )
            )
            paid.status = "pagado"
            session.add(paid)

            # Pending colegiatura → lets you test the Cobrar flow.
            session.add(
                Charge(
                    student_id=student.id,
                    description="COLEGIATURA AGOSTO",
                    amount=3410,
                    due_date=TODAY + timedelta(days=10),
                    created_by=admin.id,
                )
            )
            logger.info("demo charges + payment %s created", folio)
        else:
            logger.info("demo student already present, only refreshed fiscal header")

        await session.commit()
    logger.info("demo data ready — open Tesorería → Caja and search 62626011")


if __name__ == "__main__":
    asyncio.run(main())
