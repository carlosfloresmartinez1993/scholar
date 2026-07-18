"""Email-code login: request stores only a hash, verify issues a session,
codes are single-use, and wrong/expired codes are rejected."""
import re
from datetime import timedelta

from sqlmodel import select

from app.models import User
from app.models.common import utcnow

from tests.conftest import SUPERUSER_EMAIL


async def test_login_code_flow(client, session_factory, monkeypatch):
    sent = {}
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes, "send_email", lambda *, to, subject, html: sent.update(html=html)
    )

    # request: always ok, code lands only in the email
    r = await client.post("/api/v1/auth/login-code/request", json={"email": SUPERUSER_EMAIL})
    assert r.status_code == 200 and r.json() == {"ok": True}
    code = re.search(r">(\d{6})<", sent["html"]).group(1)

    async with session_factory() as session:
        user = (await session.exec(select(User).where(User.email == SUPERUSER_EMAIL))).first()
        from app.api.routes.auth import _login_code_digest

        assert user.login_code_hash == _login_code_digest(code)
        assert code not in user.login_code_hash  # never stored in the clear

    # wrong code rejected
    bad = "000000" if code != "000000" else "111111"
    r = await client.post(
        "/api/v1/auth/login-code/verify", json={"email": SUPERUSER_EMAIL, "code": bad}
    )
    assert r.status_code == 400

    # right code: session cookies issued
    r = await client.post(
        "/api/v1/auth/login-code/verify", json={"email": SUPERUSER_EMAIL, "code": code}
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == SUPERUSER_EMAIL
    assert "access_token" in r.cookies

    # single-use: the same code no longer works
    r = await client.post(
        "/api/v1/auth/login-code/verify", json={"email": SUPERUSER_EMAIL, "code": code}
    )
    assert r.status_code == 400


async def test_login_code_unknown_email_is_silent(client):
    r = await client.post(
        "/api/v1/auth/login-code/request", json={"email": "nadie@inue.edu.mx"}
    )
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_login_code_expired(client, session_factory, monkeypatch):
    sent = {}
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes, "send_email", lambda *, to, subject, html: sent.update(html=html)
    )
    r = await client.post("/api/v1/auth/login-code/request", json={"email": SUPERUSER_EMAIL})
    assert r.status_code == 200
    code = re.search(r">(\d{6})<", sent["html"]).group(1)

    async with session_factory() as session:
        user = (await session.exec(select(User).where(User.email == SUPERUSER_EMAIL))).first()
        user.login_code_expires = utcnow() - timedelta(minutes=1)
        session.add(user)
        await session.commit()

    r = await client.post(
        "/api/v1/auth/login-code/verify", json={"email": SUPERUSER_EMAIL, "code": code}
    )
    assert r.status_code == 400


async def test_login_code_cooldown_is_enumeration_safe(client, monkeypatch):
    """Within the resend cooldown, known and unknown accounts answer identically
    (200 ok), and no second email goes out."""
    sends = []
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes, "send_email", lambda *, to, subject, html: sends.append(to)
    )
    for _ in range(2):
        r = await client.post(
            "/api/v1/auth/login-code/request", json={"email": SUPERUSER_EMAIL}
        )
        assert r.status_code == 200 and r.json() == {"ok": True}
        r = await client.post(
            "/api/v1/auth/login-code/request", json={"email": "nadie@inue.edu.mx"}
        )
        assert r.status_code == 200 and r.json() == {"ok": True}
    assert sends == [SUPERUSER_EMAIL]  # cooldown silently suppressed the resend
