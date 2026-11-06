"""Kárdex único del alumno: todas las materias del plan vigente, cada intento con su
RVOE, ciclo y grupo, y el desglose CF / E1 / EQ."""
from httpx import AsyncClient

from tests.conftest import login
from tests.test_academic_flow import CURP_A, build_catalog


async def enroll_student(client: AsyncClient, campus_id: str, group_id: str, **extra) -> dict:
    student = (await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Manuel Rubio", "campus_id": campus_id,
    })).json()
    response = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group_id, **extra,
    })
    assert response.status_code == 201, response.text
    return student


async def kardex(client: AsyncClient, student_id: str) -> dict:
    response = await client.get(f"/api/v1/grades/students/{student_id}/kardex-completo")
    assert response.status_code == 200, response.text
    return response.json()


async def test_kardex_lists_pending_subjects_and_grade_breakdown(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])

    components = {}
    for label, kind, weight, counts in [
        ("Parcial", "parcial", 60, True), ("Ordinario", "ordinario", 40, True),
        ("Extraordinario", "extraordinario", 0, False),
    ]:
        components[kind] = (await client.post("/api/v1/catalog/evaluation-components", json={
            "plan_subject_id": catalog["subject_a"]["id"], "kind": kind, "label": label,
            "weight_pct": weight, "counts_towards_final": counts,
        })).json()
    await client.patch(f"/api/v1/catalog/terms/{catalog['term']['id']}",
                       json={"grade_capture_open": True})
    se_id = (await client.get(
        f"/api/v1/students/{student['id']}/subject-enrollments"
    )).json()[0]["id"]
    captured = await client.post("/api/v1/grades/capture-batch", json=[
        {"subject_enrollment_id": se_id, "component_id": components[k]["id"], "value": v}
        for k, v in [("parcial", 5), ("ordinario", 5), ("extraordinario", 8)]
    ])
    assert captured.status_code == 200, captured.text

    k = await kardex(client, student["id"])
    assert k["current_plan_version_id"] == catalog["plan"]["id"]
    assert k["period_type"] == "cuatrimestral"
    taken, pending = k["rows"]  # ordered by period: DER101 (1) then DER201 (2)
    assert taken["code"] == "DER101"
    assert taken["cf"] == 5.0  # ordinario reprobada…
    assert taken["e1"] == 8.0  # …acreditada en extraordinario
    assert taken["final_grade"] == 8.0
    assert taken["status"] == "aprobada"
    assert taken["rvoe"] == catalog["rvoe"]["agreement_number"]
    assert taken["group_code"] == "LD-1A"
    assert taken["term_name"] == "2026-2"
    assert taken["recognition"] is None

    assert pending["code"] == "DER201"
    assert pending["status"] == "pendiente"
    assert pending["subject_enrollment_id"] is None
    assert pending["rvoe"] == catalog["rvoe"]["agreement_number"]
    assert k["progress"]["passed_subjects"] == 1
    assert k["progress"]["total_subjects"] == 2


async def test_kardex_spans_rvoe_change(client, seed):
    """Plan/RVOE change: one kárdex, each row with the RVOE it was taken under;
    pending subjects and progress come from the new (current) plan only."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])

    rvoe2 = (await client.post("/api/v1/catalog/rvoes", json={
        "program_id": catalog["program"]["id"], "campus_id": campus_id,
        "agreement_number": "20270002", "authority": "estatal",
        "modality": "escolarizada", "issue_date": "2027-01-10",
    })).json()
    plan2 = (await client.post("/api/v1/catalog/plan-versions", json={
        "rvoe_id": rvoe2["id"], "version_label": "2027", "period_type": "cuatrimestral",
        "periods_count": 9, "min_attendance_pct": 80,
    })).json()
    for code, period in [("LIAS101", 1), ("LIAS202", 2)]:
        await client.post("/api/v1/catalog/plan-subjects", json={
            "plan_version_id": plan2["id"], "code": code, "name": f"Materia {code}",
            "period_number": period, "credits": 7,
        })
    term2 = (await client.post("/api/v1/catalog/terms", json={
        "name": "2027-1", "period_type": "cuatrimestral",
        "start_date": "2027-01-05", "end_date": "2027-04-30",
    })).json()
    group2 = (await client.post("/api/v1/catalog/groups", json={
        "code": "LD2-1A", "period_number": 1, "plan_version_id": plan2["id"],
        "term_id": term2["id"],
    })).json()
    moved = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"],
    })
    assert moved.status_code == 201, moved.text

    k = await kardex(client, student["id"])
    assert k["current_plan_version_id"] == plan2["id"]
    by_code = {r["code"]: r for r in k["rows"]}
    assert set(by_code) == {"DER101", "LIAS101", "LIAS202"}  # DER201: old plan, never taken
    assert by_code["DER101"]["rvoe"] == "20260001"
    assert by_code["LIAS101"]["rvoe"] == "20270002"
    assert by_code["LIAS101"]["status"] == "cursando"
    assert by_code["LIAS202"]["status"] == "pendiente"
    # same period, older term first: the RVOE change reads top to bottom
    assert [r["code"] for r in k["rows"]][:2] == ["DER101", "LIAS101"]
    assert k["progress"]["total_subjects"] == 2


async def test_kardex_marks_recognition_groups(client, seed):
    """A subject held in an internal "-EQ" group shows as equivalencia (no CF)."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    eq_group = (await client.post("/api/v1/catalog/groups", json={
        "code": "LD-2026-EQ", "period_number": 1, "plan_version_id": catalog["plan"]["id"],
        "term_id": catalog["term"]["id"],
    })).json()
    student = await enroll_student(client, campus_id, eq_group["id"])

    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER101")
    assert row["recognition"] == "eq"
    assert row["final_grade"] is None  # propuesta: la equivalencia aún no sale
    assert row["cf"] is None


async def test_kardex_without_plan(client, seed):
    await login(client)
    student = (await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Sin Plan", "campus_id": str(seed["campus"].id),
    })).json()
    k = await kardex(client, student["id"])
    assert k["rows"] == []
    assert k["current_plan_version_id"] is None
