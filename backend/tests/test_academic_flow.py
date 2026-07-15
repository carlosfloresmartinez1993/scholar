"""End-to-end academic flow: catalog → RVOE blocking (RT-03) → students (RT-09)
→ enrollment with seriación (RF-C07) → grades (RF-C01/C02) → kardex (RF-C08)."""
import pytest
from httpx import AsyncClient

from tests.conftest import login

CURP_A = "RUBM010101HBCXNS09"
CURP_B = "GOMA020202MBCXNS08"


async def build_catalog(client: AsyncClient, campus_id: str) -> dict:
    """Program + vigente RVOE + plan + 2 subjects (B seriada con A) + term + group."""
    program = (await client.post("/api/v1/catalog/programs", json={
        "code": "LD", "name": "Licenciatura en Derecho", "level": "licenciatura",
    })).json()
    rvoe = (await client.post("/api/v1/catalog/rvoes", json={
        "program_id": program["id"], "campus_id": campus_id,
        "agreement_number": "20260001", "authority": "federal",
        "modality": "escolarizada", "issue_date": "2026-01-15",
    })).json()
    plan = (await client.post("/api/v1/catalog/plan-versions", json={
        "rvoe_id": rvoe["id"], "version_label": "2026", "period_type": "cuatrimestral",
        "periods_count": 9, "min_attendance_pct": 80,
    })).json()
    subject_a = (await client.post("/api/v1/catalog/plan-subjects", json={
        "plan_version_id": plan["id"], "code": "DER101",
        "name": "Introducción al Derecho", "period_number": 1, "credits": 6,
    })).json()
    subject_b = (await client.post("/api/v1/catalog/plan-subjects", json={
        "plan_version_id": plan["id"], "code": "DER201", "name": "Derecho Civil",
        "period_number": 2, "credits": 6, "prerequisite_ids": [subject_a["id"]],
    })).json()
    term = (await client.post("/api/v1/catalog/terms", json={
        "name": "2026-2", "period_type": "cuatrimestral",
        "start_date": "2026-09-01", "end_date": "2026-12-15",
    })).json()
    # campus is intentionally NOT sent: it must be derived from the plan's RVOE
    group_response = await client.post("/api/v1/catalog/groups", json={
        "code": "LD-1A", "period_number": 1, "plan_version_id": plan["id"],
        "term_id": term["id"],
    })
    assert group_response.status_code == 201, group_response.text
    group = group_response.json()
    assert group["campus_id"] == rvoe["campus_id"]  # derived, not client-supplied
    return {"program": program, "rvoe": rvoe, "plan": plan, "subject_a": subject_a,
            "subject_b": subject_b, "term": term, "group": group}


async def test_group_enrollment_autocreates_plan_enrollment(client, seed):
    """Enrolling into a group creates the plan enrollment in one act (no separate step)."""
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))
    await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"],
        "plan_subject_id": catalog["subject_a"]["id"],
    })
    student = (await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Sin Plan", "campus_id": str(seed["campus"].id),
    })).json()
    # no explicit plan-enrollment call
    enrollment = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    assert enrollment.status_code == 201, enrollment.text
    plans = (await client.get(
        f"/api/v1/students/{student['id']}/plan-enrollments"
    )).json()
    assert len(plans) == 1
    assert plans[0]["plan_version_id"] == catalog["plan"]["id"]


async def test_dashboard_pending_tasks(client, seed):
    """The work queue surfaces group-subjects with no teacher assigned."""
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))
    await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"],
        "plan_subject_id": catalog["subject_a"]["id"],
    })  # no teacher_user_id
    stats = (await client.get("/api/v1/dashboard/stats")).json()
    assert stats["pending"]["groups_without_teacher"] >= 1
    assert stats["pending"]["justifications_pending"] == 0
    assert stats["pending"]["unsigned_actas"] == 0


async def test_cross_campus_enrollment_rejected(client, seed):
    """A student can only enroll in a group of their own campus (Servo Plantel key)."""
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))  # group on campus A
    other_campus = (await client.post("/api/v1/catalog/campuses", json={
        "name": "Campus Tijuana",
    })).json()
    student_b = (await client.post("/api/v1/students", json={
        "curp": CURP_B, "full_name": "Ana Gómez", "campus_id": other_campus["id"],
    })).json()
    blocked = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student_b["id"], "group_id": catalog["group"]["id"],
    })
    assert blocked.status_code == 409, blocked.text
    assert "planteles distintos" in blocked.json()["detail"]


async def test_full_academic_flow(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)

    # --- group subjects, teacher assignment
    docente = seed["users"][[r for r in seed["users"] if r.value == "docente"][0]]
    gs_a = (await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"], "plan_subject_id": catalog["subject_a"]["id"],
        "teacher_user_id": str(docente.id), "schedule_text": "Lun 8-10",
    })).json()
    gs_b_response = await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"], "plan_subject_id": catalog["subject_b"]["id"],
    })
    assert gs_b_response.status_code == 201

    # --- student with CURP (RT-09); duplicate rejected
    student = (await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Manuel Rubio", "email": "alumno@test.mx",
        "campus_id": campus_id,
    })).json()
    assert student["enrollment_number"].startswith("INUE")
    duplicate = await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Otro", "campus_id": campus_id,
    })
    assert duplicate.status_code == 409

    # invalid CURP rejected
    invalid = await client.post("/api/v1/students", json={
        "curp": "NOPE", "full_name": "X", "campus_id": campus_id,
    })
    assert invalid.status_code == 422

    # --- plan enrollment then group enrollment; seriación blocks subject B (RF-C07)
    plan_enrollment = await client.post("/api/v1/students/plan-enrollments", json={
        "student_id": student["id"], "plan_version_id": catalog["plan"]["id"],
        "start_term_id": catalog["term"]["id"],
    })
    assert plan_enrollment.status_code == 201, plan_enrollment.text

    blocked = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    assert blocked.status_code == 409
    assert "Seriación" in blocked.json()["detail"]

    # enroll only subject A
    enrollment = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]],
    })
    assert enrollment.status_code == 201, enrollment.text

    subject_enrollments = (await client.get(
        f"/api/v1/students/{student['id']}/subject-enrollments"
    )).json()
    assert len(subject_enrollments) == 1
    se_id = subject_enrollments[0]["id"]

    # --- evaluation scheme (RF-C02): 2 parciales 30% + ordinario 40%
    components = []
    for label, kind, weight, seq in [
        ("Parcial 1", "parcial", 30, 1), ("Parcial 2", "parcial", 30, 2),
        ("Ordinario", "ordinario", 40, 3),
    ]:
        response = await client.post("/api/v1/catalog/evaluation-components", json={
            "plan_subject_id": catalog["subject_a"]["id"], "kind": kind,
            "label": label, "weight_pct": weight, "sequence": seq,
        })
        assert response.status_code == 201
        components.append(response.json())
    over = await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "parcial",
        "label": "Extra peso", "weight_pct": 50, "sequence": 4,
    })
    assert over.status_code == 400  # would exceed 100%

    # --- grade capture blocked while window closed (RF-C01)
    closed = await client.post("/api/v1/grades/capture", json={
        "subject_enrollment_id": se_id, "component_id": components[0]["id"], "value": 8,
    })
    assert closed.status_code == 409

    open_window = await client.patch(
        f"/api/v1/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True}
    )
    assert open_window.status_code == 200

    for component, value in zip(components, [8.0, 9.0, 10.0]):
        response = await client.post("/api/v1/grades/capture", json={
            "subject_enrollment_id": se_id, "component_id": component["id"], "value": value,
        })
        assert response.status_code == 200, response.text

    # final = .3*8 + .3*9 + .4*10 = 9.1 → aprobada
    grid = (await client.get(f"/api/v1/grades/group-subjects/{gs_a['id']}/grid")).json()
    row = grid["rows"][0]
    assert row["final_grade"] == 9.1
    assert row["status"] == "aprobada"

    # --- now subject B unlocks (seriación satisfied) via a period-2 group
    group2 = (await client.post("/api/v1/catalog/groups", json={
        "code": "LD-2A", "period_number": 2, "plan_version_id": catalog["plan"]["id"],
        "term_id": catalog["term"]["id"], "campus_id": campus_id,
    })).json()
    await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": group2["id"], "plan_subject_id": catalog["subject_b"]["id"],
    })
    reenroll = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"],
    })
    assert reenroll.status_code == 201, reenroll.text
    assert reenroll.json()["kind"] == "reinscripcion"  # RT-10 split

    # --- kardex & progress (RF-C05/C08)
    kardex = (await client.get(
        f"/api/v1/grades/students/{student['id']}/kardex",
        params={"plan_version_id": catalog["plan"]["id"]},
    )).json()
    assert kardex["progress"]["passed_subjects"] == 1
    assert kardex["progress"]["total_subjects"] == 2
    assert kardex["progress"]["credit_progress_pct"] == 50.0
    assert kardex["progress"]["eligible_for_degree"] is False

    # --- acta with folio (RF-C03/RF-D05)
    acta = await client.post(f"/api/v1/grades/group-subjects/{gs_a['id']}/actas")
    assert acta.status_code == 201
    assert acta.json()["folio"] == "ACT-000001"

    # --- SEP export (RT-10)
    export = await client.get(
        "/api/v1/students/exports/sep", params={"term_id": catalog["term"]["id"]}
    )
    assert export.status_code == 200
    assert CURP_A in export.text


async def test_rvoe_blocking(client, seed):
    """RT-03: cancelled RVOE blocks group creation and plan enrollment."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)

    cancelled = await client.patch(
        f"/api/v1/catalog/rvoes/{catalog['rvoe']['id']}", json={"status": "cancelado"}
    )
    assert cancelled.status_code == 200

    blocked_group = await client.post("/api/v1/catalog/groups", json={
        "code": "LD-1B", "period_number": 1, "plan_version_id": catalog["plan"]["id"],
        "term_id": catalog["term"]["id"], "campus_id": campus_id,
    })
    assert blocked_group.status_code == 409
    assert "RVOE" in blocked_group.json()["detail"]

    student = (await client.post("/api/v1/students", json={
        "curp": CURP_B, "full_name": "Ana Gómez", "campus_id": campus_id,
    })).json()
    blocked_enrollment = await client.post("/api/v1/students/plan-enrollments", json={
        "student_id": student["id"], "plan_version_id": catalog["plan"]["id"],
        "start_term_id": catalog["term"]["id"],
    })
    assert blocked_enrollment.status_code == 409


async def test_teacher_permissions(client, seed):
    """RF-C01: a teacher can only capture grades for their own subjects."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await client.patch(
        f"/api/v1/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True}
    )
    # subject taught by nobody
    gs = (await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"], "plan_subject_id": catalog["subject_a"]["id"],
    })).json()
    component = (await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "ordinario",
        "label": "Ordinario", "weight_pct": 100, "sequence": 1,
    })).json()
    student = (await client.post("/api/v1/students", json={
        "curp": CURP_B, "full_name": "Ana Gómez", "campus_id": campus_id,
    })).json()
    await client.post("/api/v1/students/plan-enrollments", json={
        "student_id": student["id"], "plan_version_id": catalog["plan"]["id"],
        "start_term_id": catalog["term"]["id"],
    })
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]],
    })
    se = (await client.get(f"/api/v1/students/{student['id']}/subject-enrollments")).json()[0]

    await login(client, "docente@inue.edu.mx")
    denied = await client.post("/api/v1/grades/capture", json={
        "subject_enrollment_id": se["id"], "component_id": component["id"], "value": 9,
    })
    assert denied.status_code == 403
