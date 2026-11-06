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

    # never ahead of the group's cuatrimestre: DER201 is 2.º, the group is 1.º
    later = await add_subjects(client, student["id"], group_id, [catalog["subject_b"]["id"]],
                               override_prerequisites=True)
    assert later.status_code == 409
    assert "posterior" in later.json()["detail"]

    # DER102 (1.º) is seriada with DER101, still in progress
    seriada = (await client.post("/api/v1/catalog/plan-subjects", json={
        "plan_version_id": catalog["plan"]["id"], "code": "DER102", "name": "Historia",
        "period_number": 1, "credits": 6, "prerequisite_ids": [catalog["subject_a"]["id"]],
    })).json()
    blocked = await add_subjects(client, student["id"], group_id, [seriada["id"]])
    assert blocked.status_code == 409
    assert "Seriación" in blocked.json()["detail"]
    allowed = await add_subjects(client, student["id"], group_id, [seriada["id"]],
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


async def test_students_of_the_groups_carrera(client, seed):
    """Enrolling into a group only offers students of that group's carrera (any of
    its RVOE); students of other carreras, or with no plan, are left out."""
    from tests.test_student_kardex import group_in_new_term, new_plan

    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    derecho = await enroll_student(client, campus_id, catalog["group"]["id"])

    # same carrera under another RVOE
    plan2 = await new_plan(client, catalog["program"]["id"], campus_id, "20270002", [("LIAS101", 1)])
    group2 = await group_in_new_term(client, plan2["id"], 1, "LD2-1A")
    other_rvoe = (await client.post("/api/v1/students", json={
        "curp": "GOMA020202MBCXNS08", "full_name": "Otro RVOE", "campus_id": campus_id,
    })).json()
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": other_rvoe["id"], "group_id": group2["id"],
    })

    # another carrera, and a student with no plan at all
    psico = (await client.post("/api/v1/catalog/programs", json={
        "code": "LP", "name": "Licenciatura en Psicología", "level": "licenciatura",
    })).json()
    plan_p = await new_plan(client, psico["id"], campus_id, "20270009", [("PSI101", 1)])
    group_p = await group_in_new_term(client, plan_p["id"], 1, "LP-1A")
    psicologo = (await client.post("/api/v1/students", json={
        "curp": "PEPJ000101HBCRRNA1", "full_name": "Psicología", "campus_id": campus_id,
    })).json()
    await client.post("/api/v1/students/group-enrollments", json={
        "student_id": psicologo["id"], "group_id": group_p["id"],
    })
    await client.post("/api/v1/students", json={
        "curp": "LOPA990505MBCRRNA2", "full_name": "Sin plan", "campus_id": campus_id,
    })

    listed = (await client.get("/api/v1/students", params={
        "carrera_of_plan_version_id": catalog["plan"]["id"],
    })).json()
    assert {s["id"] for s in listed} == {derecho["id"], other_rvoe["id"]}
    assert len((await client.get("/api/v1/students")).json()) == 4  # unfiltered: everyone


async def test_retake_an_earlier_failed_subject(client, seed):
    """In a later cuatrimestre the student retakes a failed earlier subject: it is
    the next attempt, and the capture grid flags it as recursamiento."""
    from tests.test_student_kardex import group_in_new_term

    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])  # DER101
    parcial = (await client.post("/api/v1/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "parcial",
        "label": "Final", "weight_pct": 100,
    })).json()
    await client.patch(f"/api/v1/catalog/terms/{catalog['term']['id']}",
                       json={"grade_capture_open": True})
    first = (await client.get(f"/api/v1/students/{student['id']}/subject-enrollments")).json()[0]
    await client.post("/api/v1/grades/capture", json={
        "subject_enrollment_id": first["id"], "component_id": parcial["id"], "value": 4,
    })  # reprobada

    group2 = await group_in_new_term(client, catalog["plan"]["id"], 2, "LD-2A")
    enrolled = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"],
        "override_prerequisites": True,  # DER201 needs DER101, failed
    })
    assert enrolled.status_code == 201, enrolled.text
    retake = await add_subjects(client, student["id"], group2["id"], [catalog["subject_a"]["id"]])
    assert retake.status_code == 201, retake.text
    assert retake.json()[0]["attempt_number"] == 2

    gs = next(x for x in (await client.get(f"/api/v1/catalog/groups/{group2['id']}/subjects")).json()
              if x["plan_subject_id"] == catalog["subject_a"]["id"])
    grid = (await client.get(f"/api/v1/grades/group-subjects/{gs['id']}/grid")).json()
    assert grid["rows"][0]["attempt_number"] == 2
