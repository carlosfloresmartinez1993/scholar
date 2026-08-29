"""The demo seed is the one script written to run against a live database, so
it gets held to what that implies: the cases it claims to create must actually
appear through the API, and the purge must take back exactly what it wrote and
nothing that looks like it.
"""
from datetime import date

import pytest
from sqlmodel import select

from app.demo_data import EMAIL_DOMAIN, MARKER, MAT_PREFIX, DemoBuilder, build, purge
from app.models import Student, StudentStatus, UserRole
from app.models.student import CURP_RE
from tests.conftest import login


async def _build(session_factory, seed, today: date | None = None) -> DemoBuilder:
    async with session_factory() as session:
        builder = DemoBuilder(
            session,
            seed["institution"],
            seed["campus"],
            seed["users"][UserRole.admin_sistema],
            today or date.today(),
        )
        await build(session, builder)
        await session.commit()
        return builder


async def _purge(session_factory) -> dict:
    async with session_factory() as session:
        removed = await purge(session)
        await session.commit()
        return removed


async def _students(session_factory) -> list[Student]:
    async with session_factory() as session:
        return list((await session.exec(select(Student))).all())


async def test_seed_writes_the_cases_it_documents(client, seed, session_factory):
    await _build(session_factory, seed)
    await login(client)

    rows = (await client.get("/api/v1/alumni")).json()
    by_name = {r["full_name"]: r for r in rows}

    # 1. derived period: Ana's last term, not her first
    assert by_name["DEMO Ana Beltrán Ruiz"]["egreso_term_name"] is not None
    assert by_name["DEMO Ana Beltrán Ruiz"]["titulado"] is False
    # 2. título registered against the matching program
    bruno = by_name["DEMO Bruno Cárdenas Loya"]
    assert bruno["titulado"] is True
    assert bruno["degree"]["kind"] == "titulo"
    # 3. egresado with no plan enrollment survives, with blanks
    carmen = by_name["DEMO Carmen Duarte Ponce"]
    assert carmen["program_id"] is None and carmen["egreso_term_id"] is None
    # 5. a diplomado for something else does not certify the licenciatura
    assert by_name["DEMO Elena Fuentes Ojeda"]["titulado"] is False

    stats = (await client.get("/api/v1/alumni/stats")).json()
    assert stats["egresados"] == 6  # Ana, Bruno, Carmen, Diego, Elena, Fernando
    assert stats["titulados"] == 2  # Bruno, Fernando
    assert stats["sin_plan"] == 1  # Carmen
    assert len(stats["by_term"]) >= 2  # the dashboard has a timeline to draw


async def test_the_maestria_does_not_date_the_licenciatura(client, seed, session_factory):
    """Diego finished one program and is studying another; the row must be dated
    by the program he finished."""
    await _build(session_factory, seed)
    await login(client)

    rows = (await client.get("/api/v1/alumni")).json()
    diego = [r for r in rows if r["full_name"] == "DEMO Diego Estrada Nava"]
    assert len(diego) == 1, "the plan he is still in must not produce a second row"
    assert diego[0]["level"] == "licenciatura"

    current = max(r["egreso_date"] for r in rows if r["egreso_date"])
    assert diego[0]["egreso_date"] < current or len(rows) == 1


async def test_debt_cases_land_in_the_adeudo_column(client, seed, session_factory):
    await _build(session_factory, seed)
    await login(client)

    response = await client.get("/api/v1/students", params={"with_debt": "true", "limit": "500"})
    assert response.status_code == 200, response.text
    by_name = {s["full_name"]: s for s in response.json()}

    # 7. plain overdue charge
    assert by_name["DEMO Gabriela Herrera Ríos"]["overdue_balance"] == 2500.0
    # 8. partial payment against one charge
    assert by_name["DEMO Hugo Ibarra Salas"]["overdue_balance"] == 1500.0
    # 9. one payment split across two charges
    assert by_name["DEMO Irene Juárez Peña"]["overdue_balance"] == 1500.0
    # 10. cancelled charge and cancelled payment are both non-events
    assert by_name["DEMO Javier Küng Ortiz"]["overdue_balance"] == 1500.0
    # 11. beca + condonación reduce it without money moving
    assert by_name["DEMO Karla López Vidal"]["overdue_balance"] == 1000.0
    # 12. the overpaid charge must not net against the real debt
    assert by_name["DEMO Luis Mendoza Cota"]["overdue_balance"] == 800.0
    # 13. owes money, none of it past due
    marta = by_name["DEMO Marta Núñez Ávila"]
    assert marta["overdue_balance"] == 0.0 and marta["balance"] == 2200.0


async def test_only_debtors_excludes_the_not_yet_due_student(client, seed, session_factory):
    await _build(session_factory, seed)
    await login(client)

    response = await client.get(
        "/api/v1/students",
        params={"with_debt": "true", "only_debtors": "true", "limit": "500"},
    )
    names = {s["full_name"] for s in response.json()}
    assert "DEMO Gabriela Herrera Ríos" in names
    assert "DEMO Marta Núñez Ávila" not in names, "nothing of hers is past due"
    assert "DEMO Ana Beltrán Ruiz" not in names, "no charges at all"


async def test_every_demo_curp_is_valid_and_unique(seed, session_factory):
    await _build(session_factory, seed)
    students = await _students(session_factory)
    curps = [s.curp for s in students]
    assert len(curps) == len(set(curps))
    for curp in curps:
        assert CURP_RE.match(curp), curp


async def test_purge_takes_back_everything_it_wrote(client, seed, session_factory):
    await _build(session_factory, seed)
    assert len(await _students(session_factory)) == 13

    removed = await _purge(session_factory)
    assert removed["students"] == 13
    assert not await _students(session_factory)

    await login(client)
    assert (await client.get("/api/v1/alumni")).json() == []
    assert (await client.get("/api/v1/catalog/programs")).json() == []
    assert (await client.get("/api/v1/catalog/terms")).json() == []


async def test_purge_spares_a_student_who_only_looks_like_a_demo_row(seed, session_factory):
    """A real student given a DEMO- matrícula by hand keeps their real email, so
    the three-mark rule must leave them standing."""
    async with session_factory() as session:
        session.add(
            Student(
                institution_id=seed["institution"].id,
                campus_id=seed["campus"].id,
                enrollment_number=f"{MAT_PREFIX}9999",
                curp="LOOA900101HBCNXX01",
                full_name="Alumna Real",
                email="alumna.real@inue.edu.mx",
                enrollment_notes=MARKER,  # even this one mark on its own is not enough
                status=StudentStatus.activo,
            )
        )
        await session.commit()

    await _build(session_factory, seed)
    await _purge(session_factory)

    survivors = [s.full_name for s in await _students(session_factory)]
    assert survivors == ["Alumna Real"]


async def test_seeding_twice_after_a_purge_is_clean(seed, session_factory):
    """What `--force` does: purge, then build again on the same database."""
    await _build(session_factory, seed)
    await _purge(session_factory)
    await _build(session_factory, seed)
    assert len(await _students(session_factory)) == 13


async def test_demo_rows_never_touch_the_real_matricula_counter(seed, session_factory):
    """Seeding must not shift the next real student's matrícula."""
    from app.models import FolioCounter

    await _build(session_factory, seed)
    async with session_factory() as session:
        counters = (
            await session.exec(select(FolioCounter).where(FolioCounter.series == "MAT"))
        ).all()
    assert not counters, "the demo assigns its own DEMO- matrículas"

    students = await _students(session_factory)
    assert all(s.enrollment_number.startswith(MAT_PREFIX) for s in students)
    assert all(s.email.endswith(EMAIL_DOMAIN) for s in students)


@pytest.mark.parametrize("series", ["TIT", "REC"])
async def test_demo_folios_do_not_consume_the_real_series(seed, session_factory, series):
    from app.models import FolioCounter

    await _build(session_factory, seed)
    async with session_factory() as session:
        counters = (
            await session.exec(select(FolioCounter).where(FolioCounter.series == series))
        ).all()
    assert not counters
