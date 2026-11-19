"""Inscripciones por ciclo: one compact row per group the student was in."""
from tests.test_other_group_subject import _setup

API = "/api/v1"


async def test_enrollment_history_lists_each_group(client, seed):
    catalog, second, third, student = await _setup(client, seed)
    await client.post(f"{API}/students/group-enrollments/other-group", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]]})

    history = (await client.get(f"{API}/students/{student['id']}/enrollment-history")).json()
    by_group = {h["group_code"]: h for h in history}
    assert set(by_group) == {"LD-2A", "LD-1A"}

    own = by_group["LD-2A"]
    assert (own["kind"], own["status"], own["period_number"]) == ("inscripcion", "activa", 2)
    assert own["term_name"] == catalog["term"]["name"]
    assert own["subjects"]["total"] == 1 and own["subjects"]["cursando"] == 1
    assert own["campus"] and own["plan_label"].startswith("RVOE ")

    assert by_group["LD-1A"]["kind"] == "otro_grupo"
    assert (await client.get(f"{API}/students/00000000-0000-0000-0000-000000000000/enrollment-history")).status_code == 404
