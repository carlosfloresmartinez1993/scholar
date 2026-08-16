"""What the calendar needs from the integration API to promote a cycle.

It creates next-cuatrimestre groups when a period is created, and only for
groups that still have somebody in them — «al menos 1 alumno aprobado y activo».
Answering that takes two things this API did not expose: which of our periods is
which of theirs, and whether the student is still with us.
"""
from tests.conftest import login
from tests.test_academic_flow import CURP_A, build_catalog
from tests.test_treasury_documents import make_student

KEY = {"X-API-Key": "changethis"}


async def test_terms_say_which_calendar_period_they_are(client, seed, monkeypatch):
    """Matching on dates alone gives up when two periods share a window."""
    await login(client)
    campus_id = str(seed["campus"].id)
    await build_catalog(client, campus_id)

    calendar_term = {
        "id": "8f6a5f5a-3f3f-4a7a-9e2f-0c1d2e3f4a5b",
        "code": "2026-43", "name": "Cuatrimestre Septiembre-Diciembre 2026",
        "year": 2026, "start_date": "2026-08-24", "end_date": "2026-12-12",
        "is_active": True,
    }

    async def fake_get_terms():
        return [dict(calendar_term)]

    monkeypatch.setattr("app.services.calendar.get_terms", fake_get_terms)
    imported = await client.post(
        "/api/v1/catalog/terms/import", json={"calendar_term_id": calendar_term["id"]}
    )
    assert imported.status_code == 201, imported.text

    terms = (await client.get("/api/v1/integration/terms", headers=KEY)).json()
    linked = [t for t in terms if t["calendar_term_id"] == calendar_term["id"]]
    assert len(linked) == 1
    # a period of our own, never imported, says so rather than being omitted
    assert any(t["calendar_term_id"] is None for t in terms)


async def test_enrollments_say_whether_the_student_is_still_with_us(client, seed):
    """`status` is the subject's, `student_status` is the person's. A student who
    passed in May and left in June is not a reason to reopen the group."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await make_student(client, campus_id, curp=CURP_A)
    await client.post(
        "/api/v1/students/group-enrollments",
        json={"student_id": student["id"], "group_id": catalog["group"]["id"]},
    )

    rows = (
        await client.get(
            f"/api/v1/integration/groups/{catalog['group']['id']}/enrollments", headers=KEY
        )
    ).json()
    assert rows, "the student should appear in the group's enrollments"
    assert rows[0]["student_status"] == "activo"
    assert rows[0]["status"] == "cursando"

    # take the student out and the field follows — the enrollment row does not
    await client.patch(
        f"/api/v1/students/{student['id']}", json={"status": "baja_definitiva"}
    )
    after = (
        await client.get(
            f"/api/v1/integration/groups/{catalog['group']['id']}/enrollments", headers=KEY
        )
    ).json()
    assert after[0]["student_status"] == "baja_definitiva"
