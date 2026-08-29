"""Demo/testing data for the egresados registry and the adeudo column (PR #25).

Every row this writes is TAGGED and removable. Nothing here is meant to survive
a demo: run with `--purge` and the database is back where it started.

    python -m app.demo_data --dry-run     # say what would happen, write nothing
    python -m app.demo_data               # create (refuses if already seeded)
    python -m app.demo_data --force       # purge, then create again
    python -m app.demo_data --purge       # remove every demo row
    python -m app.demo_data --yes         # required when ENVIRONMENT=production

How the tagging works — three independent marks, all three required before
anything is deleted, so a purge can never take a real student with it:

  * `enrollment_number` starts with "DEMO-". Real matrículas are "INUE000123",
    allocated from a row-locked counter; the demo deliberately does NOT touch
    that counter, so seeding never shifts the next real student's matrícula.
  * `email` ends in "@demo.invalid" — a reserved TLD (RFC 2606), so a stray
    alert or recovery mail can never reach a real inbox.
  * `enrollment_notes` carries MARKER verbatim.

The same restraint applies to folios: demo títulos and recibos use "DEMO-TIT-…"
and "DEMO-REC-…" instead of `next_folio()`, because consuming the real TIT/REC
series would renumber documents that a school actually has to account for.

Campus and institution are REUSED, never created — the demo has to appear where
staff are already looking. Terms are reused too when the calendar already has
enough history; the program, its RVOE, its plan versions and the groups are
demo-owned, so fake graduates never land in a real program's reports.
"""
import argparse
import asyncio
import logging
import sys
import uuid
from datetime import date, timedelta

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory
from app.models import (
    Campus,
    Charge,
    ChargeConcept,
    ChargeConceptKind,
    ChargeStatus,
    DegreeKind,
    DegreeRecord,
    EducationLevel,
    Group,
    GroupEnrollment,
    GroupEnrollmentKind,
    Institution,
    Modality,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PeriodType,
    PlanEnrollmentStatus,
    PlanVersion,
    Program,
    Rvoe,
    RvoeAuthority,
    RvoeStatus,
    Student,
    StudentPlanEnrollment,
    StudentRelative,
    StudentStatus,
    Term,
    User,
    UserRole,
)
from app.services import treasury

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("demo_data")

MARKER = "[[SCHOLAR-DEMO-PR25]]"
MAT_PREFIX = "DEMO-"
EMAIL_DOMAIN = "@demo.invalid"
CODE_PREFIX = "DEMO-"


# --- CURP -----------------------------------------------------------------------
# CURP_RE is ^[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[0-9A-Z]\d$ and the column is
# unique per institution. These are built to be obviously synthetic — they all
# start "DEM" and carry "XX" filler where a real CURP encodes birthplace — while
# still satisfying the validator, so a demo row can never be mistaken for a
# person's real identifier.
def _curp(index: int, birth: date, sex: str) -> str:
    return (
        f"DEM{chr(65 + index)}"
        f"{birth:%y%m%d}"
        f"{sex}"
        f"BCNXX"
        f"{index % 10}{index % 10}"
    )


class DemoBuilder:
    """Holds the ids the seed hands to itself; nothing here is exported."""

    def __init__(self, session: AsyncSession, institution: Institution, campus: Campus,
                 actor: User, today: date) -> None:
        self.session = session
        self.institution = institution
        self.campus = campus
        self.actor = actor
        self.today = today
        self.counts: dict[str, int] = {}
        self._folio = 0

    def _bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def next_folio(self, series: str) -> str:
        self._folio += 1
        return f"DEMO-{series}-{self._folio:04d}"

    # --- catalog ----------------------------------------------------------------

    async def terms(self) -> tuple[list[Term], Term]:
        """Three past terms (oldest → newest) plus a current one.

        Reuses the real calendar when it has the history: the Egresados dashboard
        buckets by period name, and "2024-1 ENE-ABR" tells the story that
        "DEMO Ciclo 1" cannot. Only invents terms when the calendar is too thin.
        """
        existing = (
            await self.session.exec(
                select(Term)
                .where(Term.institution_id == self.institution.id)
                .order_by(Term.end_date)
            )
        ).all()
        past = [t for t in existing if t.end_date < self.today]
        current = next(
            (t for t in existing if t.start_date <= self.today <= t.end_date),
            existing[-1] if existing else None,
        )
        if len(past) >= 3 and current is not None:
            logger.info("  terms: reusing %s + current %s",
                        ", ".join(t.name for t in past[-3:]), current.name)
            return list(past[-3:]), current

        logger.info("  terms: calendar has %d past term(s), creating demo terms", len(past))
        made: list[Term] = []
        for offset in (3, 2, 1):  # years back
            start = date(self.today.year - offset, 1, 15)
            term = Term(
                institution_id=self.institution.id,
                name=f"{CODE_PREFIX}{start.year} ENE-ABR",
                period_type=PeriodType.cuatrimestral,
                start_date=start,
                end_date=date(start.year, 4, 30),
                is_open=False,
            )
            self.session.add(term)
            made.append(term)
            self._bump("terms")
        current_term = Term(
            institution_id=self.institution.id,
            name=f"{CODE_PREFIX}{self.today.year} ACTUAL",
            period_type=PeriodType.cuatrimestral,
            start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=60),
            is_open=True,
        )
        self.session.add(current_term)
        self._bump("terms")
        await self.session.flush()
        return made, current_term

    async def catalog(self) -> tuple[PlanVersion, PlanVersion, Program, Program]:
        """A demo program (licenciatura) and a second one (maestría).

        Demo-owned on purpose: a fake graduate inside a real program would show up
        in that program's egresados count and in its titulación percentage, which
        are numbers someone may quote.
        """
        program = Program(
            institution_id=self.institution.id,
            code=f"{CODE_PREFIX}LIC",
            name="DEMO Licenciatura en Administración",
            level=EducationLevel.licenciatura,
        )
        master = Program(
            institution_id=self.institution.id,
            code=f"{CODE_PREFIX}MAE",
            name="DEMO Maestría en Educación",
            level=EducationLevel.maestria,
        )
        self.session.add(program)
        self.session.add(master)
        await self.session.flush()
        self._bump("programs", 2)

        plans: list[PlanVersion] = []
        for prog, periods in ((program, 9), (master, 6)):
            rvoe = Rvoe(
                program_id=prog.id,
                campus_id=self.campus.id,
                agreement_number=f"{CODE_PREFIX}{prog.code[-3:]}-0001",
                authority=RvoeAuthority.estatal,
                modality=Modality.escolarizada,
                issue_date=date(self.today.year - 6, 1, 10),
                status=RvoeStatus.vigente,
                notes=MARKER,
            )
            self.session.add(rvoe)
            await self.session.flush()
            plan = PlanVersion(
                rvoe_id=rvoe.id,
                version_label=f"{self.today.year - 6}",
                period_type=PeriodType.cuatrimestral,
                periods_count=periods,
            )
            self.session.add(plan)
            plans.append(plan)
            self._bump("rvoes")
            self._bump("plan_versions")
        await self.session.flush()
        return plans[0], plans[1], program, master

    async def group(
        self, plan: PlanVersion, term: Term, period_number: int, label: str
    ) -> Group:
        # `label` and not the version_label: both demo plans carry the same
        # label, and the group code is unique per (term, campus, code).
        code = f"{CODE_PREFIX}{label}-{period_number}"
        existing = (
            await self.session.exec(
                select(Group).where(
                    Group.term_id == term.id,
                    Group.campus_id == self.campus.id,
                    Group.code == code,
                )
            )
        ).first()
        if existing:
            return existing
        group = Group(
            plan_version_id=plan.id,
            term_id=term.id,
            campus_id=self.campus.id,
            code=code,
            period_number=period_number,
        )
        self.session.add(group)
        await self.session.flush()
        self._bump("groups")
        return group

    # --- people -----------------------------------------------------------------

    async def student(
        self, index: int, name: str, status: StudentStatus = StudentStatus.activo
    ) -> Student:
        birth = date(1998, 1 + (index % 12), 1 + (index % 27))
        sex = "M" if index % 2 else "H"
        student = Student(
            institution_id=self.institution.id,
            campus_id=self.campus.id,
            enrollment_number=f"{MAT_PREFIX}{index:04d}",
            curp=_curp(index, birth, sex),
            full_name=name,
            email=f"demo{index:02d}{EMAIL_DOMAIN}",
            status=status,
            birth_date=birth,
            enrollment_notes=MARKER,
        )
        self.session.add(student)
        await self.session.flush()
        self._bump("students")
        return student

    async def plan_enrollment(
        self, student: Student, plan: PlanVersion, start_term: Term,
        status: PlanEnrollmentStatus,
    ) -> StudentPlanEnrollment:
        enrollment = StudentPlanEnrollment(
            student_id=student.id,
            plan_version_id=plan.id,
            start_term_id=start_term.id,
            status=status,
        )
        self.session.add(enrollment)
        await self.session.flush()
        self._bump("plan_enrollments")
        return enrollment

    async def attend(
        self, student: Student, enrollment: StudentPlanEnrollment,
        plan: PlanVersion, terms: list[Term], label: str,
    ) -> None:
        """Group enrollments are what the egreso period is DERIVED from — there is
        no egreso date column anywhere — so a graduate without these comes out
        with a blank period, which is itself one of the cases below."""
        for n, term in enumerate(terms, start=1):
            group = await self.group(plan, term, n, label)
            self.session.add(
                GroupEnrollment(
                    student_id=student.id,
                    group_id=group.id,
                    plan_enrollment_id=enrollment.id,
                    kind=(
                        GroupEnrollmentKind.inscripcion if n == 1
                        else GroupEnrollmentKind.reinscripcion
                    ),
                )
            )
            self._bump("group_enrollments")
        await self.session.flush()

    async def degree(
        self, student: Student, program_name: str, kind: DegreeKind, issued: date
    ) -> None:
        self.session.add(
            DegreeRecord(
                student_id=student.id,
                kind=kind,
                program_name=program_name,
                issue_date=issued,
                folio=self.next_folio("TIT"),
                registered_by=self.actor.id,
                notes=MARKER,
            )
        )
        self._bump("degree_records")
        await self.session.flush()

    # --- money ------------------------------------------------------------------

    async def concept(self) -> ChargeConcept:
        concept = ChargeConcept(
            institution_id=self.institution.id,
            name="DEMO Colegiatura",
            kind=ChargeConceptKind.colegiatura,
            amount=2500.0,
        )
        self.session.add(concept)
        await self.session.flush()
        self._bump("charge_concepts")
        return concept

    async def charge(
        self, student: Student, concept: ChargeConcept, description: str,
        amount: float, days_ago: int, *, discount: float = 0.0,
        condoned: float = 0.0, cancelled: bool = False,
    ) -> Charge:
        charge = Charge(
            student_id=student.id,
            concept_id=concept.id,
            description=f"DEMO {description}",
            amount=amount,
            scholarship_discount=discount,
            condoned_amount=condoned,
            condoned_reason=MARKER if condoned else "",
            due_date=self.today - timedelta(days=days_ago),
            status=ChargeStatus.cancelado if cancelled else ChargeStatus.pendiente,
            created_by=self.actor.id,
        )
        self.session.add(charge)
        await self.session.flush()
        self._bump("charges")
        return charge

    async def pay(
        self, student: Student, amount: float, *, charge: Charge | None = None,
        split: list[tuple[Charge, float]] | None = None, cancelled: bool = False,
    ) -> Payment:
        payment = Payment(
            student_id=student.id,
            charge_id=charge.id if charge else None,
            amount=amount,
            method=PaymentMethod.efectivo,
            receipt_folio=self.next_folio("REC"),
            received_by=self.actor.id,
            cancelled=cancelled,
            cancel_reason=MARKER if cancelled else "",
            notes=MARKER,
        )
        self.session.add(payment)
        await self.session.flush()
        for target, part in split or []:
            self.session.add(
                PaymentAllocation(payment_id=payment.id, charge_id=target.id, amount=part)
            )
            self._bump("payment_allocations")
        self._bump("payments")
        await self.session.flush()
        return payment


# --- the dataset ----------------------------------------------------------------

async def build(session: AsyncSession, builder: DemoBuilder) -> None:
    past, current = await builder.terms()
    t_old, t_mid, t_recent = past
    lic_plan, mae_plan, lic_program, mae_program = await builder.catalog()
    touched: list[Charge] = []

    # === Egresados =============================================================

    # 1. The plain case: finished, period derived from the LAST term attended,
    #    no título registered yet.
    ana = await builder.student(1, "DEMO Ana Beltrán Ruiz", StudentStatus.egresado)
    ana_plan = await builder.plan_enrollment(
        ana, lic_plan, t_old, PlanEnrollmentStatus.egresado
    )
    await builder.attend(ana, ana_plan, lic_plan, [t_old, t_mid, t_recent], "LIC")

    # 2. Titulado, with the libro de títulos entry that backs it. The degree's
    #    program_name matches the plan's program, which is the ONLY thing that
    #    makes a row read «titulado» from the registry side.
    bruno = await builder.student(2, "DEMO Bruno Cárdenas Loya", StudentStatus.egresado)
    bruno_plan = await builder.plan_enrollment(
        bruno, lic_plan, t_old, PlanEnrollmentStatus.titulado
    )
    await builder.attend(bruno, bruno_plan, lic_plan, [t_old, t_mid, t_recent], "LIC")
    await builder.degree(
        bruno, lic_program.name, DegreeKind.titulo, t_recent.end_date + timedelta(days=120)
    )

    # 3. Marked egresado by hand, never enrolled in a plan. The row must stay,
    #    with program and period blank — dropping it would shrink the count with
    #    no explanation. Feeds `sin_plan` AND `sin_periodo`.
    await builder.student(3, "DEMO Carmen Duarte Ponce", StudentStatus.egresado)

    # 4. The attribution case: finished the licenciatura years ago, is in the
    #    maestría right now. The egresado row must be dated by the licenciatura's
    #    last term — NOT by the maestría's current one.
    diego = await builder.student(4, "DEMO Diego Estrada Nava", StudentStatus.activo)
    diego_lic = await builder.plan_enrollment(
        diego, lic_plan, t_old, PlanEnrollmentStatus.egresado
    )
    await builder.attend(diego, diego_lic, lic_plan, [t_old, t_mid], "LIC")
    diego_mae = await builder.plan_enrollment(
        diego, mae_plan, current, PlanEnrollmentStatus.inscrito
    )
    await builder.attend(diego, diego_mae, mae_plan, [current], "MAE")

    # 5. Holds a diplomado for something else entirely. It must NOT certify the
    #    licenciatura: over-claiming titulación in an official registry is the
    #    error that cannot be walked back.
    elena = await builder.student(5, "DEMO Elena Fuentes Ojeda", StudentStatus.egresado)
    elena_plan = await builder.plan_enrollment(
        elena, lic_plan, t_mid, PlanEnrollmentStatus.egresado
    )
    await builder.attend(elena, elena_plan, lic_plan, [t_mid, t_recent], "LIC")
    await builder.degree(
        elena, "DEMO Diplomado en Gestión Escolar", DegreeKind.diploma,
        t_recent.end_date + timedelta(days=60),
    )

    # 6. An older cohort, so the dashboard has more than one period to draw and
    #    the timeline reads as a timeline.
    fernando = await builder.student(6, "DEMO Fernando Gil Márquez", StudentStatus.egresado)
    fernando_plan = await builder.plan_enrollment(
        fernando, lic_plan, t_old, PlanEnrollmentStatus.titulado
    )
    await builder.attend(fernando, fernando_plan, lic_plan, [t_old], "LIC")
    await builder.degree(
        fernando, lic_program.name, DegreeKind.titulo, t_old.end_date + timedelta(days=200)
    )

    # === Adeudo ================================================================

    concept = await builder.concept()

    # 7. Straightforward debtor: one charge, past due, untouched.
    gabriela = await builder.student(7, "DEMO Gabriela Herrera Ríos")
    touched.append(await builder.charge(gabriela, concept, "Colegiatura vencida", 2500.0, 45))

    # 8. Partial payment against a single charge (Payment.charge_id).
    hugo = await builder.student(8, "DEMO Hugo Ibarra Salas")
    hugo_charge = await builder.charge(hugo, concept, "Colegiatura parcial", 2500.0, 30)
    await builder.pay(hugo, 1000.0, charge=hugo_charge)
    touched.append(hugo_charge)

    # 9. One payment split across two charges (PaymentAllocation) — the other
    #    shape money arrives in, and the one a per-charge subquery forgets.
    irene = await builder.student(9, "DEMO Irene Juárez Peña")
    irene_a = await builder.charge(irene, concept, "Colegiatura A", 2000.0, 60)
    irene_b = await builder.charge(irene, concept, "Colegiatura B", 2000.0, 30)
    await builder.pay(irene, 2500.0, split=[(irene_a, 2000.0), (irene_b, 500.0)])
    touched.extend([irene_a, irene_b])

    # 10. A cancelled charge and a cancelled payment: neither is collectible, and
    #     neither may show up as debt.
    javier = await builder.student(10, "DEMO Javier Küng Ortiz")
    javier_dead = await builder.charge(
        javier, concept, "Cargo cancelado", 3000.0, 20, cancelled=True
    )
    javier_live = await builder.charge(javier, concept, "Colegiatura viva", 1500.0, 15)
    await builder.pay(javier, 1500.0, charge=javier_live, cancelled=True)
    touched.extend([javier_dead, javier_live])

    # 11. Beca + condonación: both reduce what is owed without any money moving.
    karla = await builder.student(11, "DEMO Karla López Vidal")
    touched.append(
        await builder.charge(
            karla, concept, "Colegiatura con beca y condonación", 2500.0, 25,
            discount=500.0, condoned=1000.0,
        )
    )

    # 12. Overpaid by a few cents on one charge while genuinely owing another.
    #     The overpay must not net against the real debt — that is the floor-at-
    #     zero-per-charge rule, and it is invisible until someone overpays.
    luis = await builder.student(12, "DEMO Luis Mendoza Cota")
    luis_over = await builder.charge(luis, concept, "Colegiatura sobrepagada", 1000.0, 50)
    await builder.pay(luis, 1000.05, charge=luis_over)
    luis_real = await builder.charge(luis, concept, "Colegiatura pendiente", 800.0, 10)
    touched.extend([luis_over, luis_real])

    # 13. Owes money, but nothing is past due yet: a balance with zero vencido.
    #     She must NOT appear under «solo con adeudo», which filters on vencido.
    marta = await builder.student(13, "DEMO Marta Núñez Ávila")
    touched.append(
        await builder.charge(marta, concept, "Colegiatura futura", 2200.0, -30)
    )

    # Let the app decide each charge's status from the money actually recorded,
    # rather than hand-setting it — a demo whose statuses disagree with its
    # payments would teach the reader the wrong thing about the column.
    for charge in touched:
        if charge.status != ChargeStatus.cancelado:
            await treasury.refresh_charge_status(session, charge)


# --- purge ----------------------------------------------------------------------

async def _demo_student_ids(session: AsyncSession) -> list[uuid.UUID]:
    """All three marks required. A row that carries only one of them is not ours
    and is left alone."""
    return list(
        (
            await session.exec(
                select(Student.id).where(
                    Student.enrollment_number.like(f"{MAT_PREFIX}%"),  # type: ignore[attr-defined]
                    Student.email.like(f"%{EMAIL_DOMAIN}"),  # type: ignore[attr-defined]
                    Student.enrollment_notes == MARKER,
                )
            )
        ).all()
    )


async def purge(session: AsyncSession) -> dict[str, int]:
    """Delete demo rows, children before parents (no ON DELETE CASCADE here)."""
    removed: dict[str, int] = {}
    student_ids = await _demo_student_ids(session)

    def note(key: str, result) -> None:
        if result.rowcount:
            removed[key] = result.rowcount

    if student_ids:
        charge_ids = list(
            (
                await session.exec(
                    select(Charge.id).where(Charge.student_id.in_(student_ids))  # type: ignore[attr-defined]
                )
            ).all()
        )
        payment_ids = list(
            (
                await session.exec(
                    select(Payment.id).where(Payment.student_id.in_(student_ids))  # type: ignore[attr-defined]
                )
            ).all()
        )
        if payment_ids:
            note("payment_allocations", await session.execute(
                delete(PaymentAllocation).where(
                    PaymentAllocation.payment_id.in_(payment_ids)  # type: ignore[attr-defined]
                )
            ))
        note("payments", await session.execute(
            delete(Payment).where(Payment.student_id.in_(student_ids))  # type: ignore[attr-defined]
        ))
        if charge_ids:
            note("charges", await session.execute(
                delete(Charge).where(Charge.id.in_(charge_ids))  # type: ignore[attr-defined]
            ))
        note("degree_records", await session.execute(
            delete(DegreeRecord).where(DegreeRecord.student_id.in_(student_ids))  # type: ignore[attr-defined]
        ))
        note("group_enrollments", await session.execute(
            delete(GroupEnrollment).where(
                GroupEnrollment.student_id.in_(student_ids)  # type: ignore[attr-defined]
            )
        ))
        note("plan_enrollments", await session.execute(
            delete(StudentPlanEnrollment).where(
                StudentPlanEnrollment.student_id.in_(student_ids)  # type: ignore[attr-defined]
            )
        ))
        note("student_relatives", await session.execute(
            delete(StudentRelative).where(
                StudentRelative.student_id.in_(student_ids)  # type: ignore[attr-defined]
            )
        ))
        note("students", await session.execute(
            delete(Student).where(Student.id.in_(student_ids))  # type: ignore[attr-defined]
        ))

    note("groups", await session.exec(
        delete(Group).where(Group.code.like(f"{CODE_PREFIX}%"))  # type: ignore[attr-defined]
    ))
    note("charge_concepts", await session.exec(
        delete(ChargeConcept).where(ChargeConcept.name.like("DEMO %"))  # type: ignore[attr-defined]
    ))
    # plan versions → rvoes → programs, following the FKs upward
    demo_programs = list(
        (
            await session.exec(
                select(Program.id).where(Program.code.like(f"{CODE_PREFIX}%"))  # type: ignore[attr-defined]
            )
        ).all()
    )
    if demo_programs:
        rvoe_ids = list(
            (
                await session.exec(
                    select(Rvoe.id).where(Rvoe.program_id.in_(demo_programs))  # type: ignore[attr-defined]
                )
            ).all()
        )
        if rvoe_ids:
            note("plan_versions", await session.execute(
                delete(PlanVersion).where(PlanVersion.rvoe_id.in_(rvoe_ids))  # type: ignore[attr-defined]
            ))
            note("rvoes", await session.execute(
                delete(Rvoe).where(Rvoe.id.in_(rvoe_ids))  # type: ignore[attr-defined]
            ))
        note("programs", await session.execute(
            delete(Program).where(Program.id.in_(demo_programs))  # type: ignore[attr-defined]
        ))
    note("terms", await session.exec(
        delete(Term).where(Term.name.like(f"{CODE_PREFIX}%"))  # type: ignore[attr-defined]
    ))
    return removed


# --- entry point ----------------------------------------------------------------

async def run(*, do_purge: bool, force: bool, dry_run: bool) -> int:
    async with async_session_factory() as session:
        institution = (await session.exec(select(Institution))).first()
        if institution is None:
            logger.error("No institution — run `python -m app.initial_data` first.")
            return 1
        campus = (
            await session.exec(
                select(Campus).where(Campus.institution_id == institution.id)
                .order_by(Campus.created_at)
            )
        ).first()
        if campus is None:
            logger.error("No campus on %s — nothing to attach students to.", institution.short_name)
            return 1
        actor = (
            await session.exec(
                select(User).where(User.role == UserRole.admin_sistema).order_by(User.email)
            )
        ).first()
        if actor is None:
            logger.error("No admin_sistema user to attribute charges and folios to.")
            return 1

        existing = await _demo_student_ids(session)
        logger.info("institution=%s campus=%s actor=%s", institution.short_name, campus.name, actor.email)
        logger.info("demo students currently present: %d", len(existing))

        if do_purge or (force and existing):
            if dry_run:
                logger.info("[dry-run] would purge %d demo student(s) and their rows", len(existing))
            else:
                removed = await purge(session)
                await session.commit()
                logger.info("purged: %s", removed or "nothing")
            if do_purge:
                return 0

        if existing and not force:
            logger.info("Already seeded — re-run with --force to rebuild, or --purge to remove.")
            return 0

        if dry_run:
            logger.info("[dry-run] would create 13 demo students "
                        "(6 egresados cases + 7 adeudo cases), a demo program, "
                        "its maestría, their RVOEs/plans, groups, charges and payments")
            return 0

        builder = DemoBuilder(session, institution, campus, actor, date.today())
        await build(session, builder)
        await session.commit()
        logger.info("created: %s", builder.counts)
        logger.info("Egresados → /egresados   Adeudo → /alumnos (Solo con adeudo)")
        logger.info("Remove it all with: python -m app.demo_data --purge")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purge", action="store_true", help="remove every demo row")
    parser.add_argument("--force", action="store_true", help="purge, then seed again")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--yes", action="store_true",
                        help="required to write when ENVIRONMENT=production")
    args = parser.parse_args()

    writing = not args.dry_run
    if settings.ENVIRONMENT == "production" and writing and not args.yes:
        logger.error(
            "Refusing to write demo data to ENVIRONMENT=production without --yes.\n"
            "This puts synthetic students, charges and payments into the live "
            "registry. They are tagged and `--purge` removes them, but reports "
            "and exports will include them until you do."
        )
        sys.exit(2)

    sys.exit(asyncio.run(run(do_purge=args.purge, force=args.force, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
