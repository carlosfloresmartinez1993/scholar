"""Wizard student payload: server-side full_name composition, nested relatives,
and validation of postal code / previous GPA. Legacy payloads keep working."""
from tests.conftest import login

CURP = "GOMC010203HBCNRL09"


async def test_wizard_create_composes_full_name_and_relatives(client, seed):
    await login(client)
    response = await client.post("/api/v1/students", json={
        "curp": CURP,
        "first_names": "Carlos",
        "last_name_p": "Gómez",
        "last_name_m": "Martínez",
        "sex": "M",
        "birth_date": "2001-02-03",
        "birth_country": "México",
        "street": "Av. Reforma",
        "ext_no": "123",
        "postal_code": "22800",
        "phone_home": "6461234567",
        "previous_school": "CBTIS 41",
        "previous_gpa": 8.7,
        "campus_id": str(seed["campus"].id),
        "relatives": [
            {"name": "María Martínez", "relationship": "madre", "phone": "6467654321"},
            {"name": "Juan Gómez", "relationship": "padre"},
        ],
    })
    assert response.status_code == 201, response.text
    student = response.json()
    assert student["full_name"] == "Carlos Gómez Martínez"
    assert student["previous_gpa"] == 8.7

    relatives = (
        await client.get(f"/api/v1/students/{student['id']}/relatives")
    ).json()
    assert {r["name"] for r in relatives} == {"María Martínez", "Juan Gómez"}

    # delete one
    rid = relatives[0]["id"]
    response = await client.delete(
        f"/api/v1/students/{student['id']}/relatives/{rid}"
    )
    assert response.status_code == 200
    remaining = (
        await client.get(f"/api/v1/students/{student['id']}/relatives")
    ).json()
    assert len(remaining) == 1


async def test_wizard_validations(client, seed):
    await login(client)
    base = {"curp": CURP, "first_names": "Ana", "last_name_p": "López",
            "campus_id": str(seed["campus"].id)}
    response = await client.post(
        "/api/v1/students", json={**base, "postal_code": "228"}
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/v1/students", json={**base, "previous_gpa": 11}
    )
    assert response.status_code == 422
    # neither full_name nor name parts -> rejected
    response = await client.post("/api/v1/students", json={
        "curp": CURP, "campus_id": str(seed["campus"].id),
    })
    assert response.status_code == 422


async def test_legacy_full_name_payload_still_works(client, seed):
    await login(client)
    response = await client.post("/api/v1/students", json={
        "curp": CURP, "full_name": "Alumno Legado",
        "campus_id": str(seed["campus"].id),
    })
    assert response.status_code == 201, response.text
    assert response.json()["full_name"] == "Alumno Legado"
