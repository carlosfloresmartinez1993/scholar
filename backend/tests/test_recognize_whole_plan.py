"""Reconocer estudios previos sobre todo el plan del RVOE, el grupo real del alumno
(el activo más alto) y lo que la promoción e inscripción deben respetar."""
from datetime import date, timedelta

from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student, kardex

API = "/api/v1"
REASON = "captura equivocada"


async def subject(client, catalog, code, period, **extra):
    return (await client.post(f"{API}/catalog/plan-subjects", json={
        "plan_version_id": catalog["plan"]["id"], "code": code, "name": f"Materia {code}",
        "period_number": period, "credits": 6, **extra,
    })).json()


async def group(client, catalog, code, period, term_id=None, **extra):
    response = await client.post(f"{API}/catalog/groups", json={
        "code": code, "period_number": period, "plan_version_id": catalog["plan"]["id"],
        "term_id": term_id or catalog["term"]["id"], **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def candidates(client, student, catalog):
    response = await client.get(f"{API}/students/{student['id']}/recognitions/candidates",
                                params={"plan_version_id": catalog["plan"]["id"]})
    assert response.status_code == 200, response.text
    return response.json()


async def recognize(client, student, catalog, *items):
    return await client.post(f"{API}/students/{student['id']}/recognitions", json={
        "plan_version_id": catalog["plan"]["id"], "items": list(items),
    })


def eq(subject_row, grade=None):
    return {"plan_subject_id": subject_row["id"], "kind": "eq", "grade": grade, "origin": "Dictamen 1"}


async def test_any_subject_of_the_plan_can_be_recognized(client, seed):
    """In 2.º, a subject of 3.º from another school; the group stays 2.º."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    ahead = await subject(client, catalog, "DER301", 3)
    group2 = await group(client, catalog, "LD-2A", 2)
    student = await enroll_student(client, campus_id, group2["id"], override_prerequisites=True)

    data = await candidates(client, student, catalog)
    states = {s["code"]: s["state"] for s in data["subjects"]}
    assert states == {"DER101": "libre", "DER201": "en_curso", "DER301": "libre"}

    response = await recognize(client, student, catalog, eq(ahead))
    assert response.status_code == 201, response.text
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER301")
    assert (row["recognition"], row["period_number"], row["final_grade"]) == ("eq", 3, None)

    current = (await client.get(f"{API}/students/{student['id']}/current-group")).json()
    assert current["code"] == "LD-2A"  # recognized ahead, not in 3.º


async def test_subject_in_course_without_evaluations_is_replaced(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])  # DER101, en curso

    response = await recognize(client, student, catalog, eq(catalog["subject_a"], 9))
    assert response.status_code == 201, response.text
    rows = [r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER101"]
    assert [(r["recognition"], r["final_grade"]) for r in rows] == [("eq", 9)]
    # still in the group: a student never stays without one
    current = (await client.get(f"{API}/students/{student['id']}/current-group")).json()
    assert current["id"] == catalog["group"]["id"]

    again = await recognize(client, student, catalog, eq(catalog["subject_a"]))
    assert again.status_code == 409
    assert "ya está reconocida" in again.json()["detail"]


async def test_subject_with_evaluations_cannot_be_marked_until_corrected(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    component = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "parcial", "label": "Final", "weight_pct": 100,
    })).json()
    await client.patch(f"{API}/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True})
    [se] = (await client.get(f"{API}/students/{student['id']}/subject-enrollments")).json()
    await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": se["id"], "component_id": component["id"], "value": 4,
    })  # reprobada

    data = await candidates(client, student, catalog)
    assert next(s for s in data["subjects"] if s["code"] == "DER101")["state"] == "evaluada"
    refused = await recognize(client, student, catalog, eq(catalog["subject_a"]))
    assert refused.status_code == 409
    assert "tiene evaluaciones registradas" in refused.json()["detail"]

    # the grade is corrected first; then it can be marked
    assert (await client.post(f"{API}/grades/subject-enrollments/{se['id']}/correct", json={
        "reason": REASON, "components": [{"component_id": component["id"], "value": None}],
    })).status_code == 200
    assert (await recognize(client, student, catalog, eq(catalog["subject_a"]))).status_code == 201


async def test_retake_in_a_lower_group_is_not_the_students_group(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)  # LD-1A is 1.º
    group4 = await group(client, catalog, "LD-4A", 4)
    student = await enroll_student(client, campus_id, group4["id"])
    enrolled = await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
    })
    assert enrolled.status_code == 201, enrolled.text  # later and lower: a recursamiento
    current = (await client.get(f"{API}/students/{student['id']}/current-group")).json()
    assert current["code"] == "LD-4A"
    assert (await candidates(client, student, catalog))["group_code"] == "LD-4A"


async def _term_soon(client, name="2027-1"):
    today = date.today()
    return (await client.post(f"{API}/catalog/terms", json={
        "name": name, "period_type": "cuatrimestral",
        "start_date": (today + timedelta(days=5)).isoformat(),
        "end_date": (today + timedelta(days=120)).isoformat(),
    })).json()


async def test_promotion_respects_recognitions_and_retakes(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    term2 = await _term_soon(client)
    await group(client, catalog, "LD-2A", 2, term2["id"], promotes_from_group_id=catalog["group"]["id"])
    student = await enroll_student(client, campus_id, catalog["group"]["id"])

    # a subject added to the group for a retake is not asked of the others
    other_id = (await client.post(f"{API}/students", json={
        "curp": "GOMA020202MBCXNS08", "full_name": "Otro", "campus_id": campus_id,
    })).json()["id"]
    await client.post(f"{API}/students/group-enrollments", json={
        "student_id": other_id, "group_id": catalog["group"]["id"],
    })

    # EQ without a grade yet: the dictamen stands, it advances
    assert (await recognize(client, student, catalog, eq(catalog["subject_a"]))).status_code == 201
    # DER201 (2.º) is also recognized: promoted, it is not taken again
    assert (await recognize(client, student, catalog, eq(catalog["subject_b"]))).status_code == 201

    preview = (await client.post(f"{API}/students/promote-cycle?dry_run=false")).json()
    assert [p["student"] for p in preview["promoted"]] == ["Manuel Rubio"]
    assert {s["student"]: s["reason"] for s in preview["skipped"]}["Otro"] == "no acreditó el periodo"

    k = await kardex(client, student["id"])
    assert [(r["code"], r["recognition"]) for r in k["rows"]] == [("DER101", "eq"), ("DER201", "eq")]
    current = (await client.get(f"{API}/students/{student['id']}/current-group")).json()
    assert current["code"] == "LD-2A"


async def test_pending_recognition_counts_for_seriacion(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group2 = await group(client, catalog, "LD-2A", 2)
    student = (await client.post(f"{API}/students", json={
        "curp": "GOMA020202MBCXNS08", "full_name": "Otra", "campus_id": campus_id,
    })).json()
    blocked = await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"],
    })
    assert blocked.status_code == 409  # DER201 needs DER101
    await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"], "override_prerequisites": True,
        "plan_subject_ids": [],
    })
    assert (await recognize(client, student, catalog, eq(catalog["subject_a"]))).status_code == 201
    third = await subject(client, catalog, "DER301", 2, prerequisite_ids=[catalog["subject_a"]["id"]])
    added = await client.post(f"{API}/students/group-enrollments/subjects", json={
        "student_id": student["id"], "group_id": group2["id"], "plan_subject_ids": [third["id"]],
    })
    assert added.status_code == 201, added.text
