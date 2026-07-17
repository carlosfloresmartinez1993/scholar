"""Wizard intake: one POST creates the student (full capture + relatives) and
enrolls them into the group, reusing matrícula/plan/auto-billing logic."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog

CURP = "PELJ990101HBCXRN08"


async def test_wizard_intake_creates_and_enrolls(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)

    response = await client.post("/api/v1/students/intake", json={
        "group_id": catalog["group"]["id"],
        "student": {
            "curp": CURP,
            "first_names": "Juan",
            "last_name_p": "Pérez",
            "last_name_m": "López",
            "sex": "M",
            "campus_id": campus_id,
            "email": "juan@test.mx",
            "relatives": [{"name": "Rosa López", "relationship": "madre"}],
        },
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["student"]["full_name"] == "Juan Pérez López"
    assert body["student"]["enrollment_number"]
    assert body["enrollment"]["group_id"] == catalog["group"]["id"]
    assert body["enrollment"]["kind"] == "inscripcion"

    sid = body["student"]["id"]
    relatives = (await client.get(f"/api/v1/students/{sid}/relatives")).json()
    assert [r["name"] for r in relatives] == ["Rosa López"]


async def test_wizard_intake_missing_group(client, seed):
    await login(client)
    response = await client.post("/api/v1/students/intake", json={
        "group_id": "00000000-0000-0000-0000-000000000000",
        "student": {
            "curp": CURP, "full_name": "X Y",
            "campus_id": str(seed["campus"].id),
        },
    })
    assert response.status_code == 404
