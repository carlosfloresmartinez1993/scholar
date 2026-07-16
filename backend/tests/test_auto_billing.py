"""Automatic per-cuatrimestre billing (RF-T02): enrolling a student into a group
generates the enrollment fee + monthly colegiaturas from the tabulador; scholarships
(pct-only, colegiatura-only, whole-career) freeze onto the colegiaturas."""
from httpx import AsyncClient

from tests.conftest import login
from tests.test_academic_flow import CURP_A, CURP_B, build_catalog
from tests.test_treasury_documents import make_student

SEP_DEC = {"2026-09-01", "2026-10-01", "2026-11-01", "2026-12-01"}


async def _tabulador(client: AsyncClient, *, inscripcion=3000, reinscripcion=2800, colegiatura=2500):
    """Seed the price table (global: no program/modality scope)."""
    for name, kind, amount in [
        ("Inscripción", "inscripcion", inscripcion),
        ("Reinscripción", "reinscripcion", reinscripcion),
        ("Colegiatura", "colegiatura", colegiatura),
    ]:
        await client.post("/api/v1/treasury/concepts", json={
            "name": name, "kind": kind, "amount": amount,
        })


async def _charges(client: AsyncClient, student_id: str) -> list[dict]:
    statement = (await client.get(
        f"/api/v1/treasury/students/{student_id}/statement"
    )).json()
    return statement["charges"]


async def test_enrollment_generates_fee_and_monthly_colegiaturas(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    student = await make_student(client, campus_id)

    enroll = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    assert enroll.status_code == 201, enroll.text
    assert enroll.json()["kind"] == "inscripcion"

    charges = await _charges(client, student["id"])
    fee = [c for c in charges if c["description"].startswith("Inscripción")]
    cole = [c for c in charges if c["description"].startswith("Colegiatura")]

    assert len(fee) == 1
    assert fee[0]["amount"] == 3000
    assert fee[0]["due_date"] == "2026-09-01"  # term start
    assert fee[0]["scholarship_discount"] == 0

    assert len(cole) == 4  # one per month Sep-Dec
    assert {c["due_date"] for c in cole} == SEP_DEC
    assert all(c["amount"] == 2500 for c in cole)


async def test_waive_enrollment_fee(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    student = await make_student(client, campus_id)

    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
        "waive_enrollment_fee": True,
    })
    charges = await _charges(client, student["id"])
    assert not [c for c in charges if c["description"].startswith("Inscripción")]
    assert len([c for c in charges if c["description"].startswith("Colegiatura")]) == 4


async def test_scholarship_discounts_colegiatura_only(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    student = await make_student(client, campus_id)

    sch = (await client.post("/api/v1/treasury/scholarships", json={
        "student_id": student["id"], "name": "Beca 50%", "pct": 50,
        "valid_from": "2026-01-01",
    })).json()
    await client.post(f"/api/v1/treasury/scholarships/{sch['id']}/authorize")

    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    charges = await _charges(client, student["id"])
    fee = next(c for c in charges if c["description"].startswith("Inscripción"))
    cole = [c for c in charges if c["description"].startswith("Colegiatura")]

    assert fee["scholarship_discount"] == 0  # beca never touches the enrollment fee
    assert all(c["scholarship_discount"] == 1250 for c in cole)  # 50% of 2500
    assert all(c["balance"] == 1250 for c in cole)


async def test_scholarship_retroapplies_on_authorize(client, seed):
    """A beca granted AFTER the student was billed retro-applies to open colegiaturas."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    student = await make_student(client, campus_id)

    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    # billed with no active beca yet → no discount
    charges = await _charges(client, student["id"])
    assert all(c["scholarship_discount"] == 0
               for c in charges if c["description"].startswith("Colegiatura"))

    sch = (await client.post("/api/v1/treasury/scholarships", json={
        "student_id": student["id"], "name": "Beca tardía", "pct": 40,
        "valid_from": "2026-01-01",
    })).json()
    await client.post(f"/api/v1/treasury/scholarships/{sch['id']}/authorize")

    charges = await _charges(client, student["id"])
    cole = [c for c in charges if c["description"].startswith("Colegiatura")]
    assert all(c["scholarship_discount"] == 1000 for c in cole)  # 40% of 2500, retro
    fee = next(c for c in charges if c["description"].startswith("Inscripción"))
    assert fee["scholarship_discount"] == 0


async def test_cohort_backfill_idempotent_and_requires_price(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]
    student = await make_student(client, campus_id)

    # No tabulador yet → enrollment is not blocked, just unbilled (best-effort).
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group_id,
    })
    assert await _charges(client, student["id"]) == []

    # Seed everything EXCEPT colegiatura, so the 409 is specifically about the
    # missing colegiatura price (not the fee concepts).
    r1 = await client.post("/api/v1/treasury/concepts", json={
        "name": "Inscripción", "kind": "inscripcion", "amount": 3000})
    r2 = await client.post("/api/v1/treasury/concepts", json={
        "name": "Reinscripción", "kind": "reinscripcion", "amount": 2800})
    assert r1.status_code == 201 and r2.status_code == 201
    missing = await client.post(f"/api/v1/treasury/groups/{group_id}/generate-charges")
    assert missing.status_code == 409

    # Add the colegiatura price, then backfill the whole group.
    await client.post("/api/v1/treasury/concepts", json={
        "name": "Colegiatura", "kind": "colegiatura", "amount": 2500})
    res = (await client.post(f"/api/v1/treasury/groups/{group_id}/generate-charges")).json()
    assert res["students_billed"] == 1
    assert res["charges_created"] == 5  # 1 inscripción + 4 colegiaturas

    # Idempotent: a second run bills nobody.
    again = (await client.post(f"/api/v1/treasury/groups/{group_id}/generate-charges")).json()
    assert again["students_billed"] == 0 and again["charges_created"] == 0


async def test_reinscripcion_repeats_billing_next_term(client, seed):
    """Each cuatrimestre is billed independently — a second enrollment charges
    reinscripción + its own colegiaturas (this is also how a repeated term re-bills)."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    student = await make_student(client, campus_id)

    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })

    # Second term + group (same period_number 1 = repeating the cuatrimestre).
    term2 = (await client.post("/api/v1/catalog/terms", json={
        "name": "2027-1", "period_type": "cuatrimestral",
        "start_date": "2027-01-05", "end_date": "2027-04-20",
    })).json()
    group2 = (await client.post("/api/v1/catalog/groups", json={
        "code": "LD-1B", "period_number": 1, "plan_version_id": catalog["plan"]["id"],
        "term_id": term2["id"],
    })).json()

    enroll2 = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"],
        "override_prerequisites": True,
    })
    assert enroll2.status_code == 201, enroll2.text
    assert enroll2.json()["kind"] == "reinscripcion"

    charges = await _charges(client, student["id"])
    assert len([c for c in charges if c["description"].startswith("Inscripción")]) == 1
    assert len([c for c in charges if c["description"].startswith("Reinscripción")]) == 1
    # 4 colegiaturas per term x 2 terms
    assert len([c for c in charges if c["description"].startswith("Colegiatura")]) == 8


async def test_cohort_backfills_only_missing_slots(client, seed):
    """Per-slot idempotency: if only colegiatura was priced at enroll time, a later
    cohort run with the fee configured adds ONLY the missing enrollment fee."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]
    await client.post("/api/v1/treasury/concepts", json={
        "name": "Colegiatura", "kind": "colegiatura", "amount": 2500})
    student = await make_student(client, campus_id)

    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group_id,
    })
    assert len(await _charges(client, student["id"])) == 4  # colegiaturas only, no fee

    # price the fee, then backfill → exactly the one missing inscripción slot is added
    await client.post("/api/v1/treasury/concepts", json={
        "name": "Inscripción", "kind": "inscripcion", "amount": 3000})
    res = (await client.post(f"/api/v1/treasury/groups/{group_id}/generate-charges")).json()
    assert res["charges_created"] == 1
    charges = await _charges(client, student["id"])
    assert len([c for c in charges if c["description"].startswith("Inscripción")]) == 1
    assert len([c for c in charges if c["description"].startswith("Colegiatura")]) == 4
