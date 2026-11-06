"""El extraordinario solo aplica a quien reprobó el ordinario."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student


async def setup(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    subject_id = catalog["subject_a"]["id"]
    comps = {}
    for label, kind, weight in [("P1", "parcial", 50), ("P2", "parcial", 50),
                                ("Extra", "extraordinario", 0)]:
        comps[label] = (await client.post("/api/v1/catalog/evaluation-components", json={
            "plan_subject_id": subject_id, "kind": kind, "label": label, "weight_pct": weight,
        })).json()["id"]
    await client.patch(f"/api/v1/catalog/terms/{catalog['term']['id']}",
                       json={"grade_capture_open": True})
    se_id = (await client.get(
        f"/api/v1/students/{student['id']}/subject-enrollments"
    )).json()[0]["id"]

    async def capture(**values):
        return await client.post("/api/v1/grades/capture-batch", json=[
            {"subject_enrollment_id": se_id, "component_id": comps[k], "value": v}
            for k, v in values.items()
        ])

    async def enrollment():
        return (await client.get(f"/api/v1/students/{student['id']}/subject-enrollments")).json()[0]

    return capture, enrollment


async def test_extraordinario_needs_a_failed_ordinario(client, seed):
    capture, enrollment = await setup(client, seed)

    incomplete = await capture(P1=5, Extra=8)  # P2 missing: ordinario unknown
    assert incomplete.status_code == 409
    assert "ordinarias" in incomplete.json()["detail"]

    assert (await capture(P1=8, P2=9)).status_code == 200  # aprobada, 8.5
    passed = await capture(Extra=10)
    assert passed.status_code == 409
    assert "aprobó el ordinario" in passed.json()["detail"]
    assert (await enrollment())["final_grade"] == 8.5


async def test_extraordinario_replaces_failed_and_drops_when_fixed(client, seed):
    capture, enrollment = await setup(client, seed)

    # same batch, extraordinario listed first: parciales are applied before it
    response = await capture(Extra=8, P1=5, P2=5)
    assert response.status_code == 200, response.text
    row = await enrollment()
    assert row["final_grade"] == 8.0
    assert row["status"] == "aprobada"

    # the teacher fixes a parcial and the student actually passed the ordinario:
    # the extraordinario no longer applies
    assert (await capture(P1=9, P2=7)).status_code == 200
    row = await enrollment()
    assert row["final_grade"] == 8.0  # (9 + 7) / 2, from the ordinario
    assert row["status"] == "aprobada"
    assert (await capture(P1=10, P2=10)).status_code == 200
    assert (await enrollment())["final_grade"] == 10.0
