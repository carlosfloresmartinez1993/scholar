"""«Cursar materia en otro grupo»: a student of a later cuatrimestre takes a pending
subject with another group that teaches it. Their group stays the same, nothing is
billed and they are not promoted from that group."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_auto_billing import _charges, _tabulador
from tests.test_treasury_documents import make_student

API = "/api/v1"


async def _setup(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    base = {"plan_version_id": catalog["plan"]["id"], "term_id": catalog["term"]["id"]}
    second = (await client.post(f"{API}/catalog/groups", json={
        **base, "code": "LD-2A", "period_number": 2})).json()
    third = (await client.post(f"{API}/catalog/groups", json={
        **base, "code": "LD-3A", "period_number": 3})).json()
    await _tabulador(client)
    student = await make_student(client, campus_id)
    # in 2nd without the 1st-cuatrimestre subject (seriación skipped on purpose)
    enrolled = await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": second["id"], "override_prerequisites": True})
    assert enrolled.status_code == 201, enrolled.text
    return catalog, second, third, student


async def test_take_a_pending_subject_in_another_group(client, seed):
    catalog, second, third, student = await _setup(client, seed)
    first = catalog["group"]  # LD-1A teaches subject A (1st cuatrimestre)
    charges_before = len(await _charges(client, student["id"]))

    options = (await client.get(
        f"{API}/students/{student['id']}/other-groups",
        params={"plan_subject_id": catalog["subject_a"]["id"]})).json()
    assert [o["code"] for o in options] == ["LD-1A"]

    taken = await client.post(f"{API}/students/group-enrollments/other-group", json={
        "student_id": student["id"], "group_id": first["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]]})
    assert taken.status_code == 201, taken.text
    assert len(taken.json()) == 1

    # still in their own group; no inscripción nor colegiaturas for it
    current = (await client.get(f"{API}/students/{student['id']}/current-group")).json()
    assert current["id"] == second["id"]
    assert len(await _charges(client, student["id"])) == charges_before

    # they show in that group's list (so the grade is captured there), marked
    roster = {r["student_id"]: r for r in (await client.get(
        f"{API}/catalog/groups/{first['id']}/students")).json()}
    assert roster[student["id"]]["subjects_only"] is True
    # but are not billed with that group
    billing = (await client.get(f"{API}/treasury/groups/{first['id']}/billing-status")).json()
    assert student["id"] not in {b["student_id"] for b in billing}

    # the kárdex shows the subject in course in LD-1A
    kardex = (await client.get(f"{API}/grades/students/{student['id']}/kardex-completo")).json()
    row = next(r for r in kardex["rows"] if r["plan_subject_id"] == catalog["subject_a"]["id"])
    assert (row["status"], row["group_code"]) == ("cursando", "LD-1A")

    # taking it again anywhere, or a group change from there, is refused
    again = await client.post(f"{API}/students/group-enrollments/other-group", json={
        "student_id": student["id"], "group_id": first["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]]})
    assert again.status_code == 409
    change = await client.post(f"{API}/students/{student['id']}/group-change", json={
        "from_group_id": first["id"], "to_group_id": second["id"]})
    assert change.status_code == 409


async def test_other_group_rules(client, seed):
    catalog, second, third, student = await _setup(client, seed)
    item = {"student_id": student["id"], "plan_subject_ids": [catalog["subject_b"]["id"]]}
    # their own group: that is «Agregar materias»
    own = await client.post(f"{API}/students/group-enrollments/other-group",
                            json={**item, "group_id": second["id"]})
    assert own.status_code == 409 and "propio grupo" in own.json()["detail"]
    # a later cuatrimestre: no taking subjects ahead (the RVOE)
    ahead = await client.post(f"{API}/students/group-enrollments/other-group",
                              json={**item, "group_id": third["id"]})
    assert ahead.status_code == 409 and "adelantar" in ahead.json()["detail"]
    # a subject the group doesn't teach
    not_taught = await client.post(f"{API}/students/group-enrollments/other-group",
                                   json={**item, "group_id": catalog["group"]["id"]})
    assert not_taught.status_code == 400
