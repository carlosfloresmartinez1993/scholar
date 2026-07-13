"""Student schedule proxy: /students/{id}/calendar merges published blocks from
the calendar system (calendar.inue.online) for the student's linked groups."""
import uuid

import app.services.calendar as calendar_service
from tests.conftest import login
from tests.test_academic_flow import CURP_A, build_catalog

CANNED_BLOCK = {
    "id": "7e5a1a2e-6f6a-4c3c-9c39-6a1c1d2e3f40",
    "subject": "Derecho Civil",
    "professor": "Dra. Ana Torres",
    "classroom": "Aula 3",
    "classroom_is_virtual": False,
    "start_date": "2026-09-01",
    "end_date": "2026-12-15",
    "group_codes": ["LD-1A"],
    "meetings": [
        {"weekday": 0, "start_time": "08:00:00", "end_time": "10:00:00"},
        {"weekday": 2, "start_time": "08:00:00", "end_time": "10:00:00"},
    ],
}


async def test_student_calendar(client, seed, monkeypatch):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)

    student = (await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Manuel Rubio", "campus_id": campus_id,
    })).json()
    await client.post("/api/v1/students/plan-enrollments", json={
        "student_id": student["id"], "plan_version_id": catalog["plan"]["id"],
        "start_term_id": catalog["term"]["id"],
    })
    gs = await client.post("/api/v1/catalog/group-subjects", json={
        "group_id": catalog["group"]["id"],
        "plan_subject_id": catalog["subject_a"]["id"],
    })
    assert gs.status_code == 201, gs.text
    enrollment = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student["id"], "group_id": catalog["group"]["id"],
        "plan_subject_ids": [catalog["subject_a"]["id"]],
    })
    assert enrollment.status_code == 201, enrollment.text

    # group not linked to the calendar -> linked: false, no upstream call
    response = await client.get(f"/api/v1/students/{student['id']}/calendar")
    assert response.status_code == 200
    assert response.json() == {"items": [], "linked": False}

    # link the group to a calendar group
    calendar_group_id = str(uuid.uuid4())
    patched = await client.patch(
        f"/api/v1/catalog/groups/{catalog['group']['id']}",
        json={"calendar_group_id": calendar_group_id},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["calendar_group_id"] == calendar_group_id

    calls: list[str] = []

    async def fake_get_schedule(group_id, term_id=None):
        calls.append(str(group_id))
        return [CANNED_BLOCK]

    monkeypatch.setattr(calendar_service, "get_schedule", fake_get_schedule)

    response = await client.get(f"/api/v1/students/{student['id']}/calendar")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["linked"] is True
    assert calls == [calendar_group_id]
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["group_code"] == catalog["group"]["code"]
    assert item["subject"] == CANNED_BLOCK["subject"]
    assert item["meetings"] == CANNED_BLOCK["meetings"]
