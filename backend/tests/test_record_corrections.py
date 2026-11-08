"""El error humano existe: corregir EQ/REV/CONV, calificaciones del historial y
revertir un cambio de RVOE."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student, group_in_new_term, kardex

API = "/api/v1"
REASON = "captura equivocada"


async def plan_b(client, campus_id, catalog):
    """Another plan with a subject below 2.º and a group of 2.º in the same term."""
    program = (await client.post(f"{API}/catalog/programs", json={
        "code": "LA", "name": "Licenciatura en Administración", "level": "licenciatura",
    })).json()
    rvoe = (await client.post(f"{API}/catalog/rvoes", json={
        "program_id": program["id"], "campus_id": campus_id, "agreement_number": "20260002",
        "authority": "federal", "modality": "escolarizada", "issue_date": "2026-01-15",
    })).json()
    plan = (await client.post(f"{API}/catalog/plan-versions", json={
        "rvoe_id": rvoe["id"], "version_label": "2026", "period_type": "cuatrimestral",
        "periods_count": 9, "min_attendance_pct": 80,
    })).json()
    low = (await client.post(f"{API}/catalog/plan-subjects", json={
        "plan_version_id": plan["id"], "code": "ADM101", "name": "Administración I",
        "period_number": 1, "credits": 6,
    })).json()
    current = (await client.post(f"{API}/catalog/plan-subjects", json={
        "plan_version_id": plan["id"], "code": "ADM201", "name": "Administración II",
        "period_number": 2, "credits": 6,
    })).json()
    group = (await client.post(f"{API}/catalog/groups", json={
        "code": "LA-2A", "period_number": 2, "plan_version_id": plan["id"],
        "term_id": catalog["term"]["id"],
    })).json()
    return {"program": program, "plan": plan, "low": low, "current": current, "group": group}


async def change(client, student, catalog, target, *decisions):
    response = await client.post(f"{API}/students/{student['id']}/rvoe-change", json={
        "from_plan_version_id": catalog["plan"]["id"], "target_group_id": target["group"]["id"],
        "decisions": list(decisions),
    })
    assert response.status_code == 200, response.text
    return response.json()


async def test_correct_and_remove_recognition(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    target = await plan_b(client, campus_id, catalog)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    await change(client, student, catalog, target,
                 {"plan_subject_id": target["low"]["id"], "action": "eq", "grade": None})

    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "ADM101")
    assert row["recognition"] == "eq" and row["final_grade"] is None

    # it was a convalidación with a 9, from another document
    url = f"{API}/students/subject-enrollments/{row['subject_enrollment_id']}"
    fixed = await client.patch(f"{url}/recognition", json={
        "kind": "conv", "grade": 9, "origin": "Dictamen 12/2026", "reason": REASON,
    })
    assert fixed.status_code == 200, fixed.text
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "ADM101")
    assert (row["recognition"], row["final_grade"], row["status"], row["origin"]) == (
        "conv", 9, "aprobada", "Dictamen 12/2026")

    # and back to pending: the grade was not official yet
    pending = await client.patch(f"{url}/recognition", json={
        "kind": "conv", "grade": None, "origin": "Dictamen 12/2026", "reason": REASON,
    })
    assert pending.status_code == 200
    k = await kardex(client, student["id"])
    row = next(r for r in k["rows"] if r["code"] == "ADM101")
    assert row["final_grade"] is None and row["status"] == "cursando"

    # it should not have been recognized: the subject stays in its period, owed
    no_reason = await client.post(f"{url}/recognition/undo", json={"reason": ""})
    assert no_reason.status_code == 422
    undone = await client.post(f"{url}/recognition/undo", json={"reason": REASON})
    assert undone.status_code == 204, undone.text
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "ADM101")
    assert (row["status"], row["period_number"]) == ("pendiente", 1)

    # it can be recognized again
    again = await client.post(f"{API}/students/{student['id']}/recognitions", json={
        "plan_version_id": target["plan"]["id"],
        "items": [{"plan_subject_id": target["low"]["id"], "kind": "conv", "grade": 8, "origin": "x"}],
    })
    assert again.status_code == 201, again.text


async def test_correct_grades_with_the_window_closed(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    parcial = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "parcial", "label": "Final", "weight_pct": 100,
    })).json()
    extra = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "extraordinario", "label": "Extra", "weight_pct": 0,
    })).json()
    term_url = f"{API}/catalog/terms/{catalog['term']['id']}"
    await client.patch(term_url, json={"grade_capture_open": True})
    [se] = (await client.get(f"{API}/students/{student['id']}/subject-enrollments")).json()
    await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": se["id"], "component_id": parcial["id"], "value": 4,
    })
    await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": se["id"], "component_id": extra["id"], "value": 7,
    })
    await client.patch(term_url, json={"grade_capture_open": False})

    url = f"{API}/grades/subject-enrollments/{se['id']}"
    form = (await client.get(f"{url}/correction")).json()
    assert form["by_components"] is True and form["final_grade"] == 7

    # direct final is refused: the components say otherwise
    direct = await client.post(f"{url}/correct", json={"reason": REASON, "final_grade": 9})
    assert direct.status_code == 409

    # the parcial was an 8: the extraordinario no longer applies
    fixed = await client.post(f"{url}/correct", json={"reason": REASON, "components": [
        {"component_id": parcial["id"], "value": 8}, {"component_id": extra["id"], "value": 7},
    ]})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json() == {"final_grade": 8, "status": "aprobada"}

    # nothing captured any more: in course again
    cleared = await client.post(f"{url}/correct", json={"reason": REASON, "components": [
        {"component_id": parcial["id"], "value": None}, {"component_id": extra["id"], "value": None},
    ]})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"final_grade": None, "status": "cursando"}

    # loaded history (no components captured): the final itself
    loaded = await client.post(f"{url}/correct", json={"reason": REASON, "final_grade": 5})
    assert loaded.json() == {"final_grade": 5, "status": "reprobada"}

    # a subject of the RVOE can't be taken off the kárdex, only its data corrected
    gone = await client.post(f"{API}/students/subject-enrollments/{se['id']}/remove-from-record",
                             json={"reason": REASON})
    assert gone.status_code in (404, 405)
    undo = await client.post(f"{API}/students/subject-enrollments/{se['id']}/recognition/undo",
                             json={"reason": REASON})
    assert undo.status_code == 400  # not a recognition
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER101")
    assert row["status"] == "reprobada" and row["period_number"] == 1


async def test_take_an_earlier_subject_never_taken(client, seed):
    """In a later period the student takes a subject of 1.º never taken: it counts in
    its own period of the plan, not in the group's."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    [first] = (await client.get(f"{API}/students/{student['id']}/subject-enrollments")).json()
    assert (await client.post(f"{API}/students/subject-enrollments/drop", json={
        "subject_enrollment_ids": [first["id"]]})).status_code == 200  # never took it
    group2 = await group_in_new_term(client, catalog["plan"]["id"], 2, "LD-2A")
    enrolled = await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"], "override_prerequisites": True,
    })
    assert enrolled.status_code == 201, enrolled.text
    added = await client.post(f"{API}/students/group-enrollments/subjects", json={
        "student_id": student["id"], "group_id": group2["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]],
    })
    assert added.status_code == 201, added.text
    assert added.json()[0]["attempt_number"] == 1
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "DER101")
    assert (row["period_number"], row["group_code"], row["status"]) == (1, "LD-2A", "cursando")


async def test_change_closes_old_group_and_revert_restores_it(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    target = await plan_b(client, campus_id, catalog)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    [se] = (await client.get(f"{API}/students/{student['id']}/subject-enrollments")).json()

    await change(client, student, catalog, target,
                 {"plan_subject_id": target["low"]["id"], "action": "conv", "grade": 9})

    # never in two RVOE: the old group and its subject in course closed
    enrollments = (await client.get(f"{API}/students/{student['id']}/group-enrollments")).json()
    assert {e["group_id"]: e["status"] for e in enrollments} == {
        catalog["group"]["id"]: "baja", target["group"]["id"]: "activa"}
    assert not (await client.get(f"{API}/grades/group-subjects/{se['group_subject_id']}/grid")).json()["rows"]

    k = await kardex(client, student["id"])
    assert k["current_plan_version_id"] == target["plan"]["id"]
    assert k["rvoe_change"]["to_rvoe"] == "20260002"

    change_id = k["rvoe_change"]["change_id"]
    response = await client.post(f"{API}/students/{student['id']}/rvoe-change/revert", json={
        "change_id": change_id, "reason": REASON,
    })
    assert response.status_code == 200, response.text

    # as it was: old plan, old group, subject in course; nothing of the new plan
    k = await kardex(client, student["id"])
    assert k["current_plan_version_id"] == catalog["plan"]["id"]
    assert k["rvoe_change"] is None
    assert k["previous"] == []
    assert [p["name"] for p in k["programs"]] == [catalog["program"]["name"]]
    assert next(r for r in k["rows"] if r["code"] == "DER101")["status"] == "cursando"
    enrollments = (await client.get(f"{API}/students/{student['id']}/group-enrollments")).json()
    assert {e["group_id"]: e["status"] for e in enrollments} == {catalog["group"]["id"]: "activa"}
    plans = (await client.get(f"{API}/students/{student['id']}/plan-enrollments")).json()
    assert [(p["plan_version_id"], p["status"]) for p in plans] == [(catalog["plan"]["id"], "inscrito")]

    twice = await client.post(f"{API}/students/{student['id']}/rvoe-change/revert", json={
        "change_id": change_id, "reason": REASON,
    })
    assert twice.status_code == 409
    assert "ya fue revertido" in twice.json()["detail"]

    # the change can be made again, right this time
    await change(client, student, catalog, target,
                 {"plan_subject_id": target["low"]["id"], "action": "eq", "grade": None})
    row = next(r for r in (await kardex(client, student["id"]))["rows"] if r["code"] == "ADM101")
    assert row["recognition"] == "eq"


async def test_revert_refused_while_new_plan_has_grades(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    target = await plan_b(client, campus_id, catalog)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    await change(client, student, catalog, target)
    component = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": target["current"]["id"], "kind": "parcial", "label": "Final", "weight_pct": 100,
    })).json()
    await client.patch(f"{API}/catalog/terms/{catalog['term']['id']}", json={"grade_capture_open": True})
    k = await kardex(client, student["id"])
    row = next(r for r in k["rows"] if r["code"] == "ADM201")
    await client.post(f"{API}/grades/capture", json={
        "subject_enrollment_id": row["subject_enrollment_id"], "component_id": component["id"], "value": 8,
    })
    url = f"{API}/students/{student['id']}/rvoe-change/revert"
    body = {"change_id": k["rvoe_change"]["change_id"], "reason": REASON}
    refused = await client.post(url, json=body)
    assert refused.status_code == 409
    assert "Administración II" in refused.json()["detail"]

    # with the capture left empty, the revert goes through
    assert (await client.post(
        f"{API}/grades/subject-enrollments/{row['subject_enrollment_id']}/correct",
        json={"reason": REASON, "components": [{"component_id": component["id"], "value": None}]},
    )).status_code == 200
    assert (await client.post(url, json=body)).status_code == 200


async def test_back_to_the_first_plan_keeps_a_kardex(client, seed):
    """A → B → A by hand instead of reverting: the kárdex still has a current plan."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    target = await plan_b(client, campus_id, catalog)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    await change(client, student, catalog, target)
    group_a2 = await group_in_new_term(client, catalog["plan"]["id"], 1, "LD-1N")
    back = await client.post(f"{API}/students/{student['id']}/rvoe-change", json={
        "from_plan_version_id": target["plan"]["id"], "target_group_id": group_a2["id"], "decisions": [],
    })
    assert back.status_code == 200, back.text
    k = await kardex(client, student["id"])
    assert k["current_plan_version_id"] == catalog["plan"]["id"]
