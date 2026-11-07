"""Baja de materia y cambio de grupo de un alumno ya inscrito."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student, kardex
from tests.test_subject_changes import add_subjects

API = "/api/v1"


async def subject_enrollments(client, student_id):
    return (await client.get(f"{API}/students/{student_id}/subject-enrollments")).json()


async def grid(client, group_subject_id):
    return (await client.get(f"{API}/grades/group-subjects/{group_subject_id}/grid")).json()


async def drop(client, ids, reason=""):
    return await client.post(f"{API}/students/subject-enrollments/drop",
                             json={"subject_enrollment_ids": ids, "reason": reason})


async def second_subject(client, catalog):
    """DER102, 1.º — so the student has two subjects in LD-1A."""
    return (await client.post(f"{API}/catalog/plan-subjects", json={
        "plan_version_id": catalog["plan"]["id"], "code": "DER102",
        "name": "Historia del Derecho", "period_number": 1, "credits": 6,
    })).json()


async def test_drop_subject(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]
    student = await enroll_student(client, campus_id, group_id)  # DER101
    extra = await second_subject(client, catalog)
    assert (await add_subjects(client, student["id"], group_id, [extra["id"]])).status_code == 201

    by_code = {}
    for se in await subject_enrollments(client, student["id"]):
        gs_list = (await client.get(f"{API}/catalog/groups/{group_id}/subjects")).json()
        gs = next(g for g in gs_list if g["id"] == se["group_subject_id"])
        by_code["DER101" if gs["plan_subject_id"] == catalog["subject_a"]["id"] else "DER102"] = se

    response = await drop(client, [by_code["DER102"]["id"]], reason="lo pidió el alumno")
    assert response.status_code == 200, response.text
    assert response.json()[0]["status"] == "baja"

    # out of the grade grid and the kárdex rows taken; still enrolled in the group
    assert not (await grid(client, by_code["DER102"]["group_subject_id"]))["rows"]
    rows = (await kardex(client, student["id"]))["rows"]
    assert not any(r["code"] == "DER102" and r["status"] == "baja" for r in rows)
    enrollments = (await client.get(f"{API}/students/{student['id']}/group-enrollments")).json()
    assert [e["status"] for e in enrollments] == ["activa"]

    again = await drop(client, [by_code["DER102"]["id"]])
    assert again.status_code == 409

    # no grades on a dropped subject
    component = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": extra["id"], "kind": "parcial", "label": "Final", "weight_pct": 100,
    })).json()
    await client.patch(f"{API}/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True})
    blocked = await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": by_code["DER102"]["id"], "component_id": component["id"], "value": 9,
    })
    assert blocked.status_code == 409

    # added back in the same group: in course again, still the first attempt
    back = await add_subjects(client, student["id"], group_id, [extra["id"]])
    assert back.status_code == 201, back.text
    assert back.json()[0]["status"] == "cursando"
    assert back.json()[0]["attempt_number"] == 1

    # dropping everything closes the group enrollment
    ids = [se["id"] for se in await subject_enrollments(client, student["id"])]
    assert (await drop(client, ids)).status_code == 200
    enrollments = (await client.get(f"{API}/students/{student['id']}/group-enrollments")).json()
    assert [e["status"] for e in enrollments] == ["baja"]


async def test_cannot_drop_graded_subject(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    component = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "parcial",
        "label": "Final", "weight_pct": 100,
    })).json()
    await client.patch(f"{API}/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True})
    [se] = await subject_enrollments(client, student["id"])
    await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": se["id"], "component_id": component["id"], "value": 8,
    })
    response = await drop(client, [se["id"]])
    assert response.status_code == 409
    assert "calificación final" in response.json()["detail"]


async def test_change_group(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_a = catalog["group"]
    student = await enroll_student(client, campus_id, group_a["id"])
    group_b = (await client.post(f"{API}/catalog/groups", json={
        "code": "LD-1B", "period_number": 1, "plan_version_id": catalog["plan"]["id"],
        "term_id": catalog["term"]["id"],
    })).json()

    # a parcial captured in A travels with the student (the evaluation is per plan subject)
    parcial = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "parcial",
        "label": "Parcial 1", "weight_pct": 50,
    })).json()
    await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "ordinario",
        "label": "Ordinario", "weight_pct": 50,
    })
    await client.patch(f"{API}/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True})
    [se] = await subject_enrollments(client, student["id"])
    await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": se["id"], "component_id": parcial["id"], "value": 9,
    })

    response = await client.post(f"{API}/students/{student['id']}/group-change", json={
        "from_group_id": group_a["id"], "to_group_id": group_b["id"], "reason": "turno",
    })
    assert response.status_code == 200, response.text
    assert response.json()["group_id"] == group_b["id"]

    enrollments = (await client.get(f"{API}/students/{student['id']}/group-enrollments")).json()
    assert {e["group_id"]: e["status"] for e in enrollments} == {
        group_a["id"]: "baja", group_b["id"]: "activa"}
    assert not (await grid(client, se["group_subject_id"]))["rows"]  # gone from A
    gs_b = (await client.get(f"{API}/catalog/groups/{group_b['id']}/subjects")).json()
    [row] = (await grid(client, gs_b[0]["id"]))["rows"]
    assert row["subject_enrollment_id"] == se["id"]
    assert row["grades"][parcial["id"]] == 9
    k = await kardex(client, student["id"])
    assert next(r for r in k["rows"] if r["code"] == "DER101")["group_code"] == "LD-1B"

    # back again to A works too (re-uses its enrollment)
    back = await client.post(f"{API}/students/{student['id']}/group-change", json={
        "from_group_id": group_b["id"], "to_group_id": group_a["id"],
    })
    assert back.status_code == 200, back.text
    # the closed group can't be revived by adding subjects to it
    blocked = await add_subjects(client, student["id"], group_b["id"], [catalog["subject_a"]["id"]])
    assert blocked.status_code == 409


async def test_change_group_rules(client, seed):
    from tests.test_student_kardex import group_in_new_term

    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    other_term = await group_in_new_term(client, catalog["plan"]["id"], 1, "LD-1Z")
    response = await client.post(f"{API}/students/{student['id']}/group-change", json={
        "from_group_id": catalog["group"]["id"], "to_group_id": other_term["id"],
    })
    assert response.status_code == 409
    assert "ciclo" in response.json()["detail"]
    same = await client.post(f"{API}/students/{student['id']}/group-change", json={
        "from_group_id": catalog["group"]["id"], "to_group_id": catalog["group"]["id"],
    })
    assert same.status_code == 400
