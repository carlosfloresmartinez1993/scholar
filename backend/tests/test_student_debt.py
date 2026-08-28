"""Adeudo column on the students list (?with_debt) and the debtors filter
(?only_debtors): the figures must equal the statement's, and the filter must run
before the LIMIT."""
from datetime import date, timedelta

from httpx import AsyncClient

from tests.conftest import login
from tests.test_academic_flow import CURP_A, CURP_B
from tests.test_treasury_documents import make_student

TODAY = date.today()
PAST = (TODAY - timedelta(days=30)).isoformat()
FUTURE = (TODAY + timedelta(days=30)).isoformat()


async def _charge(client: AsyncClient, student_id: str, description: str,
                  amount: float, due_date: str) -> dict:
    response = await client.post("/api/v1/treasury/charges", json={
        "student_id": student_id, "description": description,
        "amount": amount, "due_date": due_date,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _list(client: AsyncClient, **params) -> list[dict]:
    response = await client.get("/api/v1/students", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_debt_is_absent_unless_asked_for(client, seed):
    """None, not 0.0: a student whose adeudo was never computed is not a student
    who owes nothing, and the column must be able to tell them apart."""
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    await _charge(client, student["id"], "Colegiatura vencida", 2500, PAST)

    plain = (await _list(client))[0]
    assert plain["balance"] is None
    assert plain["overdue_balance"] is None

    with_debt = (await _list(client, with_debt=True))[0]
    assert with_debt["balance"] == 2500
    assert with_debt["overdue_balance"] == 2500


async def test_overdue_and_total_are_different_numbers(client, seed):
    """Only what is past due blocks documents (RF-T07); the column shows both."""
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    await _charge(client, student["id"], "Colegiatura vencida", 1000, PAST)
    await _charge(client, student["id"], "Colegiatura por vencer", 1500, FUTURE)

    row = (await _list(client, with_debt=True))[0]
    assert row["balance"] == 2500
    assert row["overdue_balance"] == 1000


async def test_payments_allocations_and_condonations_all_reduce_the_column(client, seed):
    """The column reads the same money the statement does — direct payments,
    multi-charge allocations and condonaciones alike."""
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    paid_direct = await _charge(client, student["id"], "Septiembre", 1000, PAST)
    split_a = await _charge(client, student["id"], "Octubre", 1000, PAST)
    split_b = await _charge(client, student["id"], "Noviembre", 1000, PAST)
    condoned = await _charge(client, student["id"], "Diciembre", 1000, PAST)

    await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_id": paid_direct["id"],
        "amount": 1000, "method": "efectivo",
    })
    await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_ids": [split_a["id"], split_b["id"]],
        "amount": 1500, "method": "transferencia",
    })
    await client.post(f"/api/v1/treasury/charges/{condoned['id']}/condone", json={
        "reason": "convenio de dirección",
    })

    statement = (await client.get(
        f"/api/v1/treasury/students/{student['id']}/statement"
    )).json()
    row = (await _list(client, with_debt=True))[0]
    assert row["balance"] == statement["balance"]
    assert row["overdue_balance"] == statement["overdue_balance"]
    assert row["balance"] == 500  # only the unallocated half of Noviembre survives


async def test_cancelled_charge_is_not_debt(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    charge = await _charge(client, student["id"], "Cargo mal capturado", 2500, PAST)
    response = await client.post(
        f"/api/v1/treasury/charges/{charge['id']}/cancel",
        params={"reason": "error de captura"},
    )
    assert response.status_code == 200, response.text

    row = (await _list(client, with_debt=True))[0]
    assert row["balance"] == 0
    assert row["overdue_balance"] == 0


async def test_overpaid_charge_does_not_cancel_another_charge_debt(client, seed):
    """Each charge is floored at zero before summing: paying 1500 against a 1000
    charge must not eat 500 of what the student still owes elsewhere."""
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    small = await _charge(client, student["id"], "Constancia", 1000, PAST)
    await _charge(client, student["id"], "Colegiatura", 2000, PAST)
    await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_id": small["id"],
        "amount": 1500, "method": "efectivo",
    })

    row = (await _list(client, with_debt=True))[0]
    assert row["balance"] == 2000
    assert row["overdue_balance"] == 2000


async def test_only_debtors_filters_before_the_limit(client, seed):
    """The filter has to be a WHERE, not a post-filter on the page: with limit=1
    the debtor must surface even though they sort second by name."""
    await login(client)
    campus_id = str(seed["campus"].id)
    solvent = await make_student(client, campus_id, curp=CURP_A)
    await client.patch(f"/api/v1/students/{solvent['id']}", json={"full_name": "Ana Solvente"})
    debtor = await make_student(client, campus_id, curp=CURP_B)
    await client.patch(f"/api/v1/students/{debtor['id']}", json={"full_name": "Zoe Deudora"})
    await _charge(client, debtor["id"], "Colegiatura vencida", 900, PAST)

    everyone = await _list(client)
    assert len(everyone) == 2

    debtors = await _list(client, only_debtors=True, with_debt=True, limit=1)
    assert [r["id"] for r in debtors] == [debtor["id"]]
    assert debtors[0]["overdue_balance"] == 900


async def test_only_debtors_ignores_future_and_settled_charges(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    not_yet_due = await make_student(client, campus_id, curp=CURP_A)
    await _charge(client, not_yet_due["id"], "Colegiatura por vencer", 800, FUTURE)

    settled = await make_student(client, campus_id, curp=CURP_B)
    charge = await _charge(client, settled["id"], "Colegiatura pagada", 800, PAST)
    await client.post("/api/v1/treasury/payments", json={
        "student_id": settled["id"], "charge_id": charge["id"],
        "amount": 800, "method": "efectivo",
    })

    assert await _list(client, only_debtors=True) == []


async def test_with_debt_still_serializes_the_rest_of_the_row(client, seed):
    """?with_debt builds StudentPublic by hand instead of letting FastAPI
    serialize the ORM row, so has_photo — a @property, not a column — has to be
    checked: losing it would blank every avatar in the list."""
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    upload = await client.post(
        f"/api/v1/students/{student['id']}/photo",
        files={"file": ("foto.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert upload.status_code == 200, upload.text

    plain = (await _list(client))[0]
    with_debt = (await _list(client, with_debt=True))[0]
    assert plain["has_photo"] is True
    assert with_debt["has_photo"] is True
    # every other field the plain list returns survives the hand-built model too
    debt_keys = ("balance", "overdue_balance")
    strip = lambda row: {k: v for k, v in row.items() if k not in debt_keys}  # noqa: E731
    assert strip(with_debt) == strip(plain)


async def test_docente_cannot_read_the_adeudo_column(client, seed):
    """The students list is AnyStaff, which includes docente — but a teacher can
    read a student's balance nowhere else (the statement is TreasuryStaff, the
    expediente is AcademicStaff). The column must not be the first place."""
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    await _charge(client, student["id"], "Colegiatura vencida", 2500, PAST)

    await login(client, "docente@inue.edu.mx")
    # the list itself still works — a teacher has always been able to read it
    plain = await client.get("/api/v1/students")
    assert plain.status_code == 200
    assert plain.json()[0]["overdue_balance"] is None

    assert (await client.get(
        "/api/v1/students", params={"with_debt": True}
    )).status_code == 403
    assert (await client.get(
        "/api/v1/students", params={"only_debtors": True}
    )).status_code == 403


async def test_treasury_and_escolares_can_read_the_adeudo_column(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    await _charge(client, student["id"], "Colegiatura vencida", 2500, PAST)

    for email in ("tesoreria@inue.edu.mx", "escolares@inue.edu.mx"):
        await login(client, email)
        rows = await _list(client, with_debt=True)
        assert rows[0]["overdue_balance"] == 2500, email
