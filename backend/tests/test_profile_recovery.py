"""Self-service profile + recovery-email verification: request→verify happy
path, wrong code, expired code and the 60s resend throttle."""
import re
from datetime import timedelta

from app.models import User, UserRole
from app.models.common import utcnow
from tests.conftest import PASSWORD, login


def capture_emails(monkeypatch):
    """Replace the outbound email sender; returns the list of sent messages."""
    sent: list[dict] = []

    def fake_send_email(*, to: str, subject: str, html: str) -> None:
        sent.append({"to": to, "subject": subject, "html": html})

    monkeypatch.setattr("app.api.routes.users.send_email", fake_send_email)
    return sent


def code_from(sent: list[dict]) -> str:
    match = re.search(r"\b(\d{6})\b", sent[-1]["html"])
    assert match, sent[-1]["html"]
    return match.group(1)


async def test_recovery_request_verify_happy_path(client, seed, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)

    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "personal@example.com"},
    )
    assert response.status_code == 200, response.text
    # the code never leaks through the API, only through the email
    assert "code" not in response.json()
    assert sent and sent[-1]["to"] == "personal@example.com"

    # candidate stays pending; the verified address is untouched until verify
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["pending_recovery_email"] == "personal@example.com"
    assert me["recovery_email"] is None

    code = code_from(sent)
    response = await client.post(
        "/api/v1/users/me/recovery-email/verify", json={"code": code}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recovery_email"] == "personal@example.com"
    assert body["recovery_email_verified"] is True
    assert body["pending_recovery_email"] is None

    # code fields are single-use: a second verify has nothing to check
    response = await client.post(
        "/api/v1/users/me/recovery-email/verify", json={"code": code}
    )
    assert response.status_code == 400


async def test_recovery_wrong_code(client, seed, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "personal@example.com"},
    )
    assert response.status_code == 200
    wrong = "000000" if code_from(sent) != "000000" else "111111"
    response = await client.post(
        "/api/v1/users/me/recovery-email/verify", json={"code": wrong}
    )
    assert response.status_code == 400
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["recovery_email_verified"] is False
    # the failed attempt didn't clobber anything: candidate is still pending
    assert me["recovery_email"] is None
    assert me["pending_recovery_email"] == "personal@example.com"


async def test_failed_attempt_keeps_verified_address(client, seed, monkeypatch):
    """A new (unverified) candidate never replaces the verified address."""
    await login(client)
    sent = capture_emails(monkeypatch)
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "primero@example.com"},
    )
    assert response.status_code == 200
    response = await client.post(
        "/api/v1/users/me/recovery-email/verify", json={"code": code_from(sent)}
    )
    assert response.status_code == 200

    # request a different address but never verify its code
    # (verify cleared sent_at, so this second request is not throttled)
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "segundo@example.com"},
    )
    assert response.status_code == 200

    me = (await client.get("/api/v1/auth/me")).json()
    assert me["recovery_email"] == "primero@example.com"
    assert me["recovery_email_verified"] is True
    assert me["pending_recovery_email"] == "segundo@example.com"


async def test_recovery_expired_code(client, seed, session_factory, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "personal@example.com"},
    )
    assert response.status_code == 200
    code = code_from(sent)

    user_id = seed["users"][UserRole.admin_sistema].id
    async with session_factory() as session:
        user = await session.get(User, user_id)
        user.recovery_code_expires = utcnow() - timedelta(minutes=1)
        session.add(user)
        await session.commit()

    response = await client.post(
        "/api/v1/users/me/recovery-email/verify", json={"code": code}
    )
    assert response.status_code == 400
    assert "expiró" in response.json()["detail"]


async def test_recovery_resend_throttle(client, seed, session_factory, monkeypatch):
    await login(client)
    capture_emails(monkeypatch)
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "personal@example.com"},
    )
    assert response.status_code == 200
    # immediate resend is rejected
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "personal@example.com"},
    )
    assert response.status_code == 429

    # a minute later the resend goes through
    user_id = seed["users"][UserRole.admin_sistema].id
    async with session_factory() as session:
        user = await session.get(User, user_id)
        user.recovery_code_sent_at = utcnow() - timedelta(seconds=61)
        session.add(user)
        await session.commit()
    response = await client.post(
        "/api/v1/users/me/recovery-email/request",
        json={"email": "personal@example.com"},
    )
    assert response.status_code == 200


async def test_profile_update(client, seed):
    await login(client)
    response = await client.patch(
        "/api/v1/users/me/profile",
        json={
            "display_name": "Admin INUE",
            "location": "Ensenada, BC",
            "position": "sistemas",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "Admin INUE"
    assert body["location"] == "Ensenada, BC"
    assert body["position"] == "sistemas"

    # changing the primary email requires the current password…
    response = await client.patch(
        "/api/v1/users/me/profile", json={"email": "nuevo@inue.edu.mx"}
    )
    assert response.status_code == 403
    response = await client.patch(
        "/api/v1/users/me/profile",
        json={"email": "nuevo@inue.edu.mx", "current_password": "not-the-password"},
    )
    assert response.status_code == 403

    # …and keeps the uniqueness validation even with the right password
    response = await client.patch(
        "/api/v1/users/me/profile",
        json={"email": "escolares@inue.edu.mx", "current_password": PASSWORD},
    )
    assert response.status_code == 409

    # explicit null is rejected, not silently applied
    response = await client.patch(
        "/api/v1/users/me/profile", json={"email": None}
    )
    assert response.status_code == 422

    # correct password → the email actually changes
    response = await client.patch(
        "/api/v1/users/me/profile",
        json={"email": "nuevo@inue.edu.mx", "current_password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "nuevo@inue.edu.mx"
