"""Roles editables (Etapa 1): each role grants views; the server checks them on every
request; new roles can be created; nobody hands out more than they have."""
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import PASSWORD, login

API = "/api/v1"

# routes that are not staff screens: login, own profile, health, the student portal
# and the integration API (it has its own key)
PUBLIC_PREFIXES = ("/api/v1/auth", "/api/v1/users/me", "/api/v1/healthz", "/api/v1/portal",
                   "/api/v1/integration", "/docs", "/openapi", "/redoc")


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def test_every_staff_endpoint_declares_a_view_permission():
    """No endpoint can slip in open: every staff route goes through require_view."""
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        dependant = getattr(route, "dependant", None)
        if dependant is None or not path.startswith("/api/v1") or path.startswith(PUBLIC_PREFIXES):
            continue
        if not any("require_view" in getattr(c, "__qualname__", "") for c in _calls(dependant)):
            missing.append(f"{sorted(route.methods)} {path}")
    assert missing == [], missing


@asynccontextmanager
async def _client_for(email):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"{API}/auth/login", data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        yield c


async def _user(client, email, role):
    r = await client.post(f"{API}/users", json={
        "email": email, "full_name": email.split("@")[0], "role": role, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


async def test_me_carries_the_role_permissions(client, seed):
    await login(client, "escolares@inue.edu.mx")
    me = (await client.get(f"{API}/auth/me")).json()
    assert {"alumnos", "grupos", "calificaciones"} <= set(me["permissions"])
    assert "tesoreria" not in me["permissions"] and "usuarios" not in me["permissions"]
    assert me["role_name"] == "Servicios Escolares" and me["own_subjects_only"] is False


async def test_a_new_role_only_reaches_its_views(client, seed):
    await login(client)
    catalog = {p["code"] for p in (await client.get(f"{API}/roles/permissions")).json()}
    assert {"alumnos", "tesoreria", "roles", "becas_autorizar"} <= catalog
    caja = await client.post(f"{API}/roles", json={"name": "Caja", "permissions": ["tesoreria"]})
    assert caja.status_code == 201, caja.text
    assert caja.json()["code"] == "caja"
    await _user(client, "caja@inue.edu.mx", "caja")

    async with _client_for("caja@inue.edu.mx") as c:
        assert (await c.get(f"{API}/treasury/scholarships")).status_code == 200
        assert (await c.get(f"{API}/students")).status_code == 200  # cobra a alumnos
        assert (await c.get(f"{API}/dashboard/stats")).status_code == 403  # no «inicio»
        assert (await c.post(f"{API}/catalog/programs", json={
            "code": "X", "name": "X", "level": "licenciatura"})).status_code == 403
        assert (await c.get(f"{API}/users")).status_code == 403
        me = (await c.get(f"{API}/auth/me")).json()
        assert me["permissions"] == ["tesoreria"]


async def test_removing_a_view_applies_at_once(client, seed):
    await login(client)
    roles = {r["code"]: r for r in (await client.get(f"{API}/roles")).json()}
    se = roles["servicios_escolares"]
    async with _client_for("escolares@inue.edu.mx") as c:
        assert (await c.get(f"{API}/catalog/terms")).status_code == 200
        assert (await c.post(f"{API}/catalog/terms", json={
            "name": "2027-2", "period_type": "cuatrimestral",
            "start_date": "2027-05-01", "end_date": "2027-08-20"})).status_code == 201
        without = [p for p in se["permissions"] if p != "periodos"]
        assert (await client.patch(f"{API}/roles/{se['id']}", json={"permissions": without})).status_code == 200
        # the very next request is refused
        assert (await c.post(f"{API}/catalog/terms", json={
            "name": "2027-3", "period_type": "cuatrimestral",
            "start_date": "2027-09-01", "end_date": "2027-12-20"})).status_code == 403
    logs = (await client.get(f"{API}/audit")).json()
    assert any(e["action"] == "role.updated" and "- periodos" in (e["detail"] or "") for e in logs)


async def test_admin_role_and_system_roles_are_protected(client, seed):
    await login(client)
    roles = {r["code"]: r for r in (await client.get(f"{API}/roles")).json()}
    admin = roles["admin_sistema"]
    assert (await client.patch(f"{API}/roles/{admin['id']}", json={"permissions": []})).status_code == 409
    assert (await client.delete(f"{API}/roles/{roles['docente']['id']}")).status_code == 409
    temp = (await client.post(f"{API}/roles", json={"name": "Temporal", "permissions": ["reportes"]})).json()
    await _user(client, "temp@inue.edu.mx", "temporal")
    assert (await client.delete(f"{API}/roles/{temp['id']}")).status_code == 409  # has users
    assert (await client.post(f"{API}/roles", json={"name": "Raro", "permissions": ["nada"]})).status_code == 422


async def test_nobody_hands_out_more_than_they_have(client, seed):
    await login(client)
    await client.post(f"{API}/roles", json={"name": "Altas", "permissions": ["usuarios"]})
    await _user(client, "altas@inue.edu.mx", "altas")
    async with _client_for("altas@inue.edu.mx") as c:
        for role in ("admin_sistema", "direccion"):
            r = await c.post(f"{API}/users", json={
                "email": f"x-{role}@inue.edu.mx", "full_name": "X", "role": role, "password": PASSWORD})
            assert r.status_code == 403, r.text
        superuser = await c.post(f"{API}/users", json={
            "email": "s@inue.edu.mx", "full_name": "S", "role": "altas", "password": PASSWORD,
            "is_superuser": True})
        assert superuser.status_code == 403
        same = await c.post(f"{API}/users", json={
            "email": "otro@inue.edu.mx", "full_name": "Otro", "role": "altas", "password": PASSWORD})
        assert same.status_code == 201


async def test_a_role_limited_to_its_own_materias(client, seed):
    await login(client)
    r = await client.post(f"{API}/roles", json={
        "name": "Adjunto", "own_subjects_only": True, "permissions": ["calificaciones", "alumnos"]})
    assert r.json()["own_subjects_only"] is True
    await _user(client, "adjunto@inue.edu.mx", "adjunto")
    async with _client_for("adjunto@inue.edu.mx") as c:
        # «alumnos» is checked as staff data: a role limited to its materias stays out
        assert (await c.get(f"{API}/students")).status_code == 403
        assert (await c.get(f"{API}/catalog/terms")).status_code == 200
