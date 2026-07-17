"""Student portal: access grant (409s, emailed password), strict guard
separation (alumno ↔ staff), and a happy-path self-scoped read."""
import re

from tests.conftest import login
from tests.test_academic_flow import build_catalog

CURP = "ROSA000101MBCXLD04"


def capture_emails(monkeypatch):
    sent: list[dict] = []

    def fake_send_email(*, to: str, subject: str, html: str) -> None:
        sent.append({"to": to, "subject": subject, "html": html})

    monkeypatch.setattr("app.api.routes.students.send_email", fake_send_email)
    return sent


def password_from(sent: list[dict]) -> str:
    match = re.search(r"Contraseña: <b>([^<]+)</b>", sent[-1]["html"])
    assert match, sent[-1]["html"]
    return match.group(1)


async def make_enrolled_student(client, seed, email="rosa@test.mx") -> dict:
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    response = await client.post("/api/v1/students/intake", json={
        "group_id": catalog["group"]["id"],
        "student": {
            "curp": CURP, "first_names": "Rosa", "last_name_p": "López",
            "email": email, "campus_id": campus_id,
        },
    })
    assert response.status_code == 201, response.text
    return response.json()["student"]


async def test_portal_access_grant_and_guards(client, seed, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)
    student = await make_enrolled_student(client, seed)

    response = await client.post(f"/api/v1/students/{student['id']}/portal-access")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "alumno"
    assert body["student_id"] == student["id"]
    assert "password" not in body
    assert sent and sent[-1]["to"] == "rosa@test.mx"
    password = password_from(sent)

    # duplicate grant -> 409
    response = await client.post(f"/api/v1/students/{student['id']}/portal-access")
    assert response.status_code == 409

    # staff can NOT read the portal
    response = await client.get("/api/v1/portal/me")
    assert response.status_code == 403

    # student logs in and is confined to /portal
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "rosa@test.mx", "password": password},
    )
    assert response.status_code == 200, response.text

    response = await client.get("/api/v1/students")
    assert response.status_code == 403  # staff endpoint rejects alumno
    response = await client.get("/api/v1/dashboard/stats")
    assert response.status_code == 403

    me = (await client.get("/api/v1/portal/me")).json()
    assert me["student"]["id"] == student["id"]
    assert me["group"] is not None

    statement = (await client.get("/api/v1/portal/statement")).json()
    assert {"charges", "payments", "balance"} <= set(statement)

    grades = (await client.get("/api/v1/portal/grades")).json()
    assert isinstance(grades, list)


async def test_portal_access_requires_email(client, seed, monkeypatch):
    await login(client)
    capture_emails(monkeypatch)
    student = await make_enrolled_student(client, seed, email="")
    response = await client.post(f"/api/v1/students/{student['id']}/portal-access")
    assert response.status_code == 409
    assert "email" in response.json()["detail"].lower()


async def test_portal_access_disable(client, seed, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)
    student = await make_enrolled_student(client, seed)
    await client.post(f"/api/v1/students/{student['id']}/portal-access")
    password = password_from(sent)

    response = await client.delete(f"/api/v1/students/{student['id']}/portal-access")
    assert response.status_code == 200
    status = (
        await client.get(f"/api/v1/students/{student['id']}/portal-access")
    ).json()
    assert status == {"exists": True, "active": False, "email": "rosa@test.mx"}

    # deactivated account can no longer log in
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "rosa@test.mx", "password": password},
    )
    assert response.status_code == 400


async def test_wizard_intake_with_portal_access(client, seed, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    response = await client.post("/api/v1/students/intake", json={
        "group_id": catalog["group"]["id"],
        "enable_portal_access": True,
        "student": {
            "curp": CURP, "first_names": "Rosa", "last_name_p": "López",
            "email": "rosa2@test.mx", "campus_id": campus_id,
        },
    })
    assert response.status_code == 201, response.text
    student = response.json()["student"]
    assert sent and sent[-1]["to"] == "rosa2@test.mx"
    status = (
        await client.get(f"/api/v1/students/{student['id']}/portal-access")
    ).json()
    assert status["exists"] is True and status["active"] is True
