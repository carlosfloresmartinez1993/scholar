"""Multi-charge cobro (RF-T03): one payment (one folio, one receipt) allocated
across several charges oldest-due-first; cancelling reopens all of them."""
from httpx import AsyncClient

from tests.conftest import login
from tests.test_treasury_documents import make_student


async def _charge(client: AsyncClient, student_id: str, description: str,
                  amount: float, due_date: str) -> dict:
    response = await client.post("/api/v1/treasury/charges", json={
        "student_id": student_id, "description": description,
        "amount": amount, "due_date": due_date,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _statement(client: AsyncClient, student_id: str) -> dict:
    return (await client.get(f"/api/v1/treasury/students/{student_id}/statement")).json()


async def test_one_payment_settles_many_charges(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    c1 = await _charge(client, student["id"], "Colegiatura septiembre", 2500, "2026-09-01")
    c2 = await _charge(client, student["id"], "Colegiatura octubre", 2500, "2026-10-01")

    response = await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_ids": [c2["id"], c1["id"]],
        "amount": 5000, "method": "efectivo",
    })
    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment["charge_id"] is None
    # allocated oldest-due-first regardless of selection order
    assert [a["charge_id"] for a in payment["allocations"]] == [c1["id"], c2["id"]]
    assert [a["amount"] for a in payment["allocations"]] == [2500, 2500]

    statement = await _statement(client, student["id"])
    assert {c["status"] for c in statement["charges"]} == {"pagado"}
    assert statement["balance"] == 0
    # one payment row, one folio
    assert len(statement["payments"]) == 1
    assert statement["payments"][0]["allocations"] == payment["allocations"]


async def test_partial_amount_covers_oldest_first(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    c1 = await _charge(client, student["id"], "Colegiatura septiembre", 2500, "2026-09-01")
    c2 = await _charge(client, student["id"], "Colegiatura octubre", 2500, "2026-10-01")

    response = await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_ids": [c1["id"], c2["id"]],
        "amount": 3000, "method": "efectivo",
    })
    assert response.status_code == 201, response.text

    statement = await _statement(client, student["id"])
    by_id = {c["id"]: c for c in statement["charges"]}
    assert by_id[c1["id"]]["status"] == "pagado"
    assert by_id[c2["id"]]["status"] == "parcial"
    assert by_id[c2["id"]]["balance"] == 2000


async def test_cancel_multi_payment_reopens_all_charges(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    c1 = await _charge(client, student["id"], "Colegiatura septiembre", 2500, "2026-09-01")
    c2 = await _charge(client, student["id"], "Colegiatura octubre", 2500, "2026-10-01")

    payment = (await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_ids": [c1["id"], c2["id"]],
        "amount": 5000, "method": "efectivo",
    })).json()

    response = await client.post(
        f"/api/v1/treasury/payments/{payment['id']}/cancel", params={"reason": "error de captura"}
    )
    assert response.status_code == 200, response.text

    statement = await _statement(client, student["id"])
    assert {c["status"] for c in statement["charges"]} == {"pendiente"}
    assert statement["balance"] == 5000


async def test_rejects_both_charge_id_and_charge_ids(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    c1 = await _charge(client, student["id"], "Colegiatura septiembre", 2500, "2026-09-01")

    response = await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_id": c1["id"], "charge_ids": [c1["id"]],
        "amount": 2500, "method": "efectivo",
    })
    assert response.status_code == 400


async def test_rejects_settled_selection(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))
    c1 = await _charge(client, student["id"], "Colegiatura septiembre", 2500, "2026-09-01")
    await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_id": c1["id"],
        "amount": 2500, "method": "efectivo",
    })

    response = await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_ids": [c1["id"]],
        "amount": 100, "method": "efectivo",
    })
    assert response.status_code == 409
