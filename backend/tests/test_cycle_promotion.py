"""Cycle promotion (Phase 8): only students who PASSED advance into their linked
next-term group and get auto-billed reinscripción. Idempotent, dry-run safe."""
from datetime import date, timedelta

from tests.conftest import login
from tests.test_academic_flow import CURP_A, CURP_B, build_catalog
from tests.test_auto_billing import _charges, _tabulador
from tests.test_treasury_documents import make_student


async def test_promote_only_passing_students(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    term1, group1 = catalog["term"], catalog["group"]  # period 1, subject_a seeded

    # one evaluation component (100%) for subject_a; open the capture window
    comp = (await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "ordinario",
        "label": "Ordinario", "weight_pct": 100, "sequence": 1,
    })).json()
    await client.patch(
        f"/api/v1/catalog/terms/{term1['id']}", json={"grade_capture_open": True}
    )

    passer = await make_student(client, campus_id, curp=CURP_A)
    failer = await make_student(client, campus_id, curp=CURP_B)

    async def enroll_and_grade(stu, value):
        await client.post("/api/v1/students/group-enrollments", json={
            "student_id": stu["id"], "group_id": group1["id"]})
        ses = (await client.get(
            f"/api/v1/students/{stu['id']}/subject-enrollments")).json()
        await client.post("/api/v1/grades/capture-batch", json=[
            {"subject_enrollment_id": ses[0]["id"], "component_id": comp["id"], "value": value}])

    await enroll_and_grade(passer, 9)  # → aprobada
    await enroll_and_grade(failer, 4)  # → reprobada

    # next-term target group, starting within the lead window, linked to group1
    today = date.today()
    term2 = (await client.post("/api/v1/catalog/terms", json={
        "name": "2027-1 ENE-ABR", "period_type": "cuatrimestral",
        "start_date": (today + timedelta(days=5)).isoformat(),
        "end_date": (today + timedelta(days=120)).isoformat(),
    })).json()
    await client.post("/api/v1/catalog/groups", json={
        "code": "LD-2A", "period_number": 2, "plan_version_id": catalog["plan"]["id"],
        "term_id": term2["id"], "promotes_from_group_id": group1["id"],
    })

    # preview: only the passer, and it changes nothing
    preview = (await client.post("/api/v1/students/promote-cycle?dry_run=true")).json()
    assert preview["dry_run"] is True
    assert {p["matricula"] for p in preview["promoted"]} == {passer["enrollment_number"]}
    assert any(
        s["matricula"] == failer["enrollment_number"] and "acredit" in s["reason"]
        for s in preview["skipped"]
    )
    assert len((await client.get(
        f"/api/v1/students/{passer['id']}/subject-enrollments")).json()) == 1  # not yet promoted

    # real run: passer enrolled in group2 + billed reinscripción
    run = (await client.post("/api/v1/students/promote-cycle?dry_run=false")).json()
    assert run["promoted_count"] == 1
    assert run["skipped_count"] >= 1
    charges = await _charges(client, passer["id"])
    assert any(c["description"].startswith("Reinscripción") for c in charges)
    assert len((await client.get(
        f"/api/v1/students/{passer['id']}/subject-enrollments")).json()) == 2  # now in group2

    # idempotent: a second run promotes nobody new
    again = (await client.post("/api/v1/students/promote-cycle?dry_run=false")).json()
    assert again["promoted_count"] == 0


async def test_promotion_needs_the_group_link(client, seed):
    """A next-term group without promotes_from_group_id is never auto-promoted."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await _tabulador(client)
    student = await make_student(client, campus_id)
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"]})

    today = date.today()
    term2 = (await client.post("/api/v1/catalog/terms", json={
        "name": "2027-1", "period_type": "cuatrimestral",
        "start_date": (today + timedelta(days=5)).isoformat(),
        "end_date": (today + timedelta(days=120)).isoformat(),
    })).json()
    # group2 WITHOUT the link
    await client.post("/api/v1/catalog/groups", json={
        "code": "LD-2A", "period_number": 2, "plan_version_id": catalog["plan"]["id"],
        "term_id": term2["id"],
    })
    preview = (await client.post("/api/v1/students/promote-cycle?dry_run=true")).json()
    assert preview["promoted_count"] == 0
