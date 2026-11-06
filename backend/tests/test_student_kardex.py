"""Kárdex único del alumno: todas las materias del plan vigente, cada intento con su
RVOE, ciclo y grupo, y el desglose CF / E1 / EQ."""
import uuid

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


async def test_extraordinario_never_blocks_the_final(client, seed, session_factory):
    """An extraordinario saved as "cuenta para final" (as the form used to allow)
    must not hold the final back: the parciales alone make it."""
    from app.models import EvaluationComponent

    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    subject_id = catalog["subject_a"]["id"]

    parciales = [(await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": subject_id, "kind": "parcial", "label": f"Parcial {n}",
        "weight_pct": 50, "sequence": n,
    })).json() for n in (1, 2)]
    extra = (await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": subject_id, "kind": "extraordinario", "label": "Extraordinario",
        "weight_pct": 0, "sequence": 3, "counts_towards_final": True,
    })).json()
    assert extra["counts_towards_final"] is False  # normalized on create

    async with session_factory() as session:  # data saved before the fix
        component = await session.get(EvaluationComponent, uuid.UUID(extra["id"]))
        component.counts_towards_final = True
        session.add(component)
        await session.commit()

    await client.patch(f"/api/v1/catalog/terms/{catalog['term']['id']}",
                       json={"grade_capture_open": True})
    se_id = (await client.get(
        f"/api/v1/students/{student['id']}/subject-enrollments"
    )).json()[0]["id"]
    await client.post("/api/v1/grades/capture-batch", json=[
        {"subject_enrollment_id": se_id, "component_id": c["id"], "value": 10} for c in parciales
    ])
    row = (await kardex(client, student["id"]))["rows"][0]
    assert row["final_grade"] == 10.0
    assert row["status"] == "aprobada"
    assert row["cf"] == 10.0


async def new_plan(client: AsyncClient, program_id: str, campus_id: str, agreement: str,
                   subjects: list[tuple[str, int]]) -> dict:
    rvoe = (await client.post("/api/v1/catalog/rvoes", json={
        "program_id": program_id, "campus_id": campus_id, "agreement_number": agreement,
        "authority": "estatal", "modality": "escolarizada", "issue_date": "2027-01-10",
    })).json()
    plan = (await client.post("/api/v1/catalog/plan-versions", json={
        "rvoe_id": rvoe["id"], "version_label": "2027", "period_type": "cuatrimestral",
        "periods_count": 9, "min_attendance_pct": 80,
    })).json()
    for code, period in subjects:
        await client.post("/api/v1/catalog/plan-subjects", json={
            "plan_version_id": plan["id"], "code": code, "name": f"Materia {code}",
            "period_number": period, "credits": 7,
        })
    return plan


async def group_in_new_term(client: AsyncClient, plan_id: str, period: int, code: str) -> dict:
    term = (await client.post("/api/v1/catalog/terms", json={
        "name": f"2027-{code}", "period_type": "cuatrimestral",
        "start_date": "2027-01-05", "end_date": "2027-04-30",
    })).json()
    return (await client.post("/api/v1/catalog/groups", json={
        "code": code, "period_number": period, "plan_version_id": plan_id, "term_id": term["id"],
    })).json()


async def test_kardex_spans_rvoe_change(client, seed):
    """Plan/RVOE change: one kárdex; each cuatrimestre under a single RVOE (the one
    it was studied under), flagged where it changes. Pending subjects and progress
    come from the new (current) plan."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])  # DER101, 1.º

    plan2 = await new_plan(client, catalog["program"]["id"], campus_id, "20270002",
                           [("LIAS101", 1), ("LIAS201", 2), ("LIAS301", 3)])
    group3 = await group_in_new_term(client, plan2["id"], 3, "LD2-3A")
    moved = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group3["id"],
    })
    assert moved.status_code == 201, moved.text

    k = await kardex(client, student["id"])
    assert k["current_plan_version_id"] == plan2["id"]
    # 1.º studied under the old RVOE: the new plan's pending LIAS101 would duplicate it
    assert [r["code"] for r in k["rows"]] == ["DER101", "LIAS201", "LIAS301"]
    statuses = {r["code"]: r["status"] for r in k["rows"]}
    assert statuses == {"DER101": "cursando", "LIAS201": "pendiente", "LIAS301": "cursando"}
    assert k["periods"] == [
        {"period_number": 1, "rvoe": "20260001", "rvoe_changed": True},
        {"period_number": 2, "rvoe": "20270002", "rvoe_changed": True},
        {"period_number": 3, "rvoe": "20270002", "rvoe_changed": False},
    ]
    assert k["progress"]["total_subjects"] == 3


async def test_kardex_one_per_carrera(client, seed):
    """Two carreras at once: a separate kárdex each, picked with program_id."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])

    program2 = (await client.post("/api/v1/catalog/programs", json={
        "code": "LP", "name": "Licenciatura en Psicología", "level": "licenciatura",
    })).json()
    plan_p = await new_plan(client, program2["id"], campus_id, "20270009", [("PSI101", 1)])
    group_p = await group_in_new_term(client, plan_p["id"], 1, "LP-1A")
    second = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group_p["id"],
    })
    assert second.status_code == 201, second.text

    k = await kardex(client, student["id"])  # default: carrera of the latest plan
    assert {p["name"] for p in k["programs"]} == {"Licenciatura en Derecho", "Licenciatura en Psicología"}
    assert k["program_id"] == program2["id"]
    assert [r["code"] for r in k["rows"]] == ["PSI101"]

    response = await client.get(
        f"/api/v1/grades/students/{student['id']}/kardex-completo",
        params={"program_id": catalog["program"]["id"]},
    )
    derecho = response.json()
    assert derecho["program_id"] == catalog["program"]["id"]
    assert [r["code"] for r in derecho["rows"]] == ["DER101", "DER201"]
    assert derecho["current_plan_version_id"] == catalog["plan"]["id"]


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
