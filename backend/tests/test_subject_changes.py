"""Materias a mitad de curso: agregarle materias del plan a un alumno ya inscrito en
el grupo, y editar los datos de una materia del plan."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student, kardex


async def add_subjects(client, student_id, group_id, subject_ids, **extra):
    return await client.post("/api/v1/students/group-enrollments/subjects", json={
        "student_id": student_id, "group_id": group_id,
        "plan_subject_ids": subject_ids, **extra,
    })


async def test_add_subject_to_enrolled_student(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])  # DER101
    group_id = catalog["group"]["id"]

    # a materia that was missing from the plan, created mid-term
    late = (await client.post("/api/v1/catalog/plan-subjects", json={
        "plan_version_id": catalog["plan"]["id"], "code": "DER102",
        "name": "Historia del Derecho", "period_number": 1, "credits": 6,
    })).json()
    response = await add_subjects(client, student["id"], group_id, [late["id"]])
    assert response.status_code == 201, response.text
    [added] = response.json()
    assert added["attempt_number"] == 1
    assert added["status"] == "cursando"

    # the group now teaches it, and the kárdex shows it in that group
    group_subjects = (await client.get(f"/api/v1/catalog/groups/{group_id}/subjects")).json()
    assert late["id"] in {gs["plan_subject_id"] for gs in group_subjects}
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER102")
    assert row["status"] == "cursando"
    assert row["group_code"] == "LD-1A"

    # no new group enrollment, so nothing billed twice
    enrollments = (await client.get(f"/api/v1/students/{student['id']}/group-enrollments")).json()
    assert len(enrollments) == 1

    again = await add_subjects(client, student["id"], group_id, [late["id"]])
    assert again.status_code == 409
    assert "ya está inscrita" in again.json()["detail"]


async def test_add_subject_rules(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    group_id = catalog["group"]["id"]

    # DER201 is seriada with DER101, still in progress
    blocked = await add_subjects(client, student["id"], group_id, [catalog["subject_b"]["id"]])
    assert blocked.status_code == 409
    assert "Seriación" in blocked.json()["detail"]
    allowed = await add_subjects(client, student["id"], group_id, [catalog["subject_b"]["id"]],
                                 override_prerequisites=True)
    assert allowed.status_code == 201, allowed.text

    other = (await client.post("/api/v1/students", json={
        "curp": "GOMA020202MBCXNS08", "full_name": "Sin grupo", "campus_id": campus_id,
    })).json()
    not_enrolled = await add_subjects(client, other["id"], group_id, [catalog["subject_a"]["id"]])
    assert not_enrolled.status_code == 404

    nothing = await add_subjects(client, student["id"], group_id, [])
    assert nothing.status_code == 400


async def test_edit_plan_subject(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    subject_id = catalog["subject_a"]["id"]

    edited = await client.patch(f"/api/v1/catalog/plan-subjects/{subject_id}", json={
        "name": "Introducción al Estudio del Derecho", "credits": 8,
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Introducción al Estudio del Derecho"
    assert edited.json()["credits"] == 8
    assert edited.json()["code"] == "DER101"  # untouched fields stay

    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER101")
    assert row["name"] == "Introducción al Estudio del Derecho"

    clash = await client.patch(f"/api/v1/catalog/plan-subjects/{subject_id}", json={"code": "DER201"})
    assert clash.status_code == 409
    empty = await client.patch(f"/api/v1/catalog/plan-subjects/{subject_id}", json={"name": "  "})
    assert empty.status_code == 400
