"""Treasury flow (RF-T01…T10), debt blocking of documents (RF-T07) and folio
sequences (RF-D05), plus attendance right-to-exam (RF-A02) and the integration
API key (RT-11)."""
from datetime import date, timedelta

from httpx import AsyncClient

from tests.conftest import login
from tests.test_academic_flow import CURP_A, build_catalog

TODAY = date.today()


async def make_student(client: AsyncClient, campus_id: str, curp: str = CURP_A) -> dict:
    response = await client.post("/api/v1/students", json={
        "curp": curp, "full_name": "Manuel Rubio", "email": "alumno@test.mx",
        "campus_id": campus_id,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def test_treasury_flow(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    student = await make_student(client, campus_id)

    concept = (await client.post("/api/v1/treasury/concepts", json={
        "name": "Colegiatura Licenciatura", "kind": "colegiatura", "amount": 2500,
    })).json()

    # 50% scholarship (RF-T05)
    scholarship = await client.post("/api/v1/treasury/scholarships", json={
        "student_id": student["id"], "name": "Beca excelencia", "pct": 50,
        "valid_from": (TODAY - timedelta(days=90)).isoformat(),
    })
    assert scholarship.status_code == 201
    both = await client.post("/api/v1/treasury/scholarships", json={
        "student_id": student["id"], "name": "Inválida", "pct": 50, "fixed_amount": 100,
        "valid_from": TODAY.isoformat(),
    })
    assert both.status_code == 400

    # payment plan of 3 monthly installments (RF-T02) with discount applied
    plan = await client.post("/api/v1/treasury/payment-plans", json={
        "student_id": student["id"], "concept_id": concept["id"],
        "installments": 3, "first_due_date": (TODAY - timedelta(days=40)).isoformat(),
    })
    assert plan.status_code == 201, plan.text
    charges = plan.json()
    assert len(charges) == 3
    assert charges[0]["scholarship_discount"] == 1250.0
    assert charges[0]["balance"] == 1250.0

    # statement shows overdue balance (first installment is 40 days old)
    statement = (await client.get(f"/api/v1/treasury/students/{student['id']}/statement")).json()
    assert statement["overdue_balance"] >= 1250.0
    assert statement["balance"] == 3750.0

    # RF-T07: debt blocks issuing a constancia
    await login(client, "escolares@inue.edu.mx")
    blocked = await client.post("/api/v1/documents/issue", json={
        "student_id": student["id"], "kind": "constancia_estudios",
    })
    assert blocked.status_code == 409
    assert "adeudo" in blocked.json()["detail"]

    # installments at -40d and -10d are both overdue; pay the first (RF-T03)
    await login(client, "tesoreria@inue.edu.mx")
    overdue_charges = [c for c in charges if c["due_date"] < TODAY.isoformat()]
    assert len(overdue_charges) == 2
    payment = (await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_id": overdue_charges[0]["id"],
        "amount": 1250, "method": "transferencia", "bank_reference": "SPEI123",
    })).json()
    assert payment["receipt_folio"] == "REC-000001"

    # still one overdue installment → still blocked (RF-T07)
    await login(client, "escolares@inue.edu.mx")
    still_blocked = await client.post("/api/v1/documents/issue", json={
        "student_id": student["id"], "kind": "constancia_estudios",
    })
    assert still_blocked.status_code == 409

    # late fees (RF-T06): 10% only on the remaining unpaid overdue charge
    await login(client, "tesoreria@inue.edu.mx")
    result = (await client.post("/api/v1/treasury/late-fees/run")).json()
    assert result["created"] == 1
    rerun = (await client.post("/api/v1/treasury/late-fees/run")).json()
    assert rerun["created"] == 0  # idempotent

    # aging report has the overdue row (RF-T08)
    aging = (await client.get("/api/v1/treasury/reports/aging")).json()
    assert any(row["bucket"] == "1-30" and row["balance"] == 1250.0 for row in aging)

    # pay the second installment → debt cleared, constancia issues (RF-T07 release)
    await client.post("/api/v1/treasury/payments", json={
        "student_id": student["id"], "charge_id": overdue_charges[1]["id"],
        "amount": 1250, "method": "efectivo",
    })
    await login(client, "escolares@inue.edu.mx")
    issued = await client.post("/api/v1/documents/issue", json={
        "student_id": student["id"], "kind": "constancia_estudios",
    })
    assert issued.status_code == 201, issued.text
    assert issued.json()["folio"] == "CON-000001"

    second = (await client.post("/api/v1/documents/issue", json={
        "student_id": student["id"], "kind": "constancia_no_adeudo",
    })).json()
    assert second["folio"] == "CNA-000001"

    # role enforcement: tesorería cannot create students
    await login(client, "tesoreria@inue.edu.mx")
    denied = await client.post("/api/v1/students", json={
        "curp": "GOMA020202MBCXNS08", "full_name": "X", "campus_id": campus_id,
    })
    assert denied.status_code == 403


async def test_attendance_right_to_exam(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    gs = (await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"], "plan_subject_id": catalog["subject_a"]["id"],
    })).json()
    student = await make_student(client, campus_id)
    await client.post("/api/v1/students/plan-enrollments", json={
        "student_id": student["id"], "plan_version_id": catalog["plan"]["id"],
        "start_term_id": catalog["term"]["id"],
    })
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]],
    })

    # 5 sessions: 3 faltas → 40% < 80% mínimo
    statuses = ["presente", "presente", "falta", "falta", "falta"]
    for i, status in enumerate(statuses):
        response = await client.post("/api/v1/attendance/sessions", json={
            "group_subject_id": gs["id"],
            "session_date": (TODAY - timedelta(days=5 - i)).isoformat(),
            "records": [{"student_id": student["id"], "status": status}],
        })
        assert response.status_code == 201, response.text

    report = (await client.get(
        f"/api/v1/attendance/group-subjects/{gs['id']}/report"
    )).json()
    assert report[0]["attendance_pct"] == 40.0
    assert report[0]["right_to_exam"] is False

    # justification approved flips faltas (RF-A04)
    justification = (await client.post("/api/v1/attendance/justifications", json={
        "student_id": student["id"], "reason": "Incapacidad médica",
        "date_from": (TODAY - timedelta(days=3)).isoformat(),
        "date_to": TODAY.isoformat(),
    })).json()
    review = await client.post(
        f"/api/v1/attendance/justifications/{justification['id']}/review",
        json={"status": "aprobado", "review_notes": "OK"},
    )
    assert review.status_code == 200

    report = (await client.get(
        f"/api/v1/attendance/group-subjects/{gs['id']}/report"
    )).json()
    assert report[0]["attendance_pct"] == 100.0
    assert report[0]["right_to_exam"] is True


async def test_integration_api_key(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    await build_catalog(client, campus_id)

    no_key = await client.get("/api/v1/integration/groups")
    assert no_key.status_code == 401

    groups = await client.get(
        "/api/v1/integration/groups", headers={"X-API-Key": "changethis"}
    )
    assert groups.status_code == 200
    assert groups.json()[0]["code"] == "LD-1A"
    assert groups.json()[0]["rvoe"] == "20260001"

    terms = await client.get(
        "/api/v1/integration/terms", headers={"X-API-Key": "changethis"}
    )
    assert terms.status_code == 200 and len(terms.json()) == 1


async def test_audit_trail(client, seed):
    """RT-08: grade changes record old and new value."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    await client.patch(
        f"/api/v1/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True}
    )
    (await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"], "plan_subject_id": catalog["subject_a"]["id"],
    })).json()
    component = (await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "ordinario",
        "label": "Ordinario", "weight_pct": 100, "sequence": 1,
    })).json()
    student = await make_student(client, campus_id)
    await client.post("/api/v1/students/plan-enrollments", json={
        "student_id": student["id"], "plan_version_id": catalog["plan"]["id"],
        "start_term_id": catalog["term"]["id"],
    })
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    se = (await client.get(f"/api/v1/students/{student['id']}/subject-enrollments")).json()[0]

    for value in (7.0, 9.0):
        await client.post("/api/v1/grades/capture", json={
            "subject_enrollment_id": se["id"], "component_id": component["id"], "value": value,
        })

    logs = (await client.get("/api/v1/audit")).json()
    update_entries = [l for l in logs if l["action"] == "grade.updated"]
    assert update_entries and "7.0 -> 9.0" in update_entries[0]["detail"]
