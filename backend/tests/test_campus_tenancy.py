"""Campus tenancy: membership (scope) enforced orthogonally to role.

A member sees/acts only within their campuses; all-campus roles (superuser /
admin_sistema) see everything. Creates are pinned/validated to the scope.
"""
from httpx import AsyncClient

from tests.conftest import PASSWORD, login

CURP_A = "RUBM010101HBCXNS09"
CURP_B = "GOMA020202MBCXNS08"


async def _make_program_rvoe(client: AsyncClient, campus_id: str, *, code: str, agreement: str):
    program = (await client.post("/api/v1/catalog/programs", json={
        "code": code, "name": f"Programa {code}", "level": "licenciatura",
    })).json()
    rvoe = (await client.post("/api/v1/catalog/rvoes", json={
        "program_id": program["id"], "campus_id": campus_id,
        "agreement_number": agreement, "authority": "federal",
        "modality": "escolarizada", "issue_date": "2026-01-15",
    })).json()
    return program, rvoe


async def test_member_list_and_create_scoped(client, seed):
    """A single-campus member: lists only their campus' students, is 403 for another."""
    await login(client)  # superuser sets up two campuses + a student in each
    campus_a = str(seed["campus"].id)
    campus_b = (await client.post("/api/v1/catalog/campuses", json={
        "name": "Campus Tijuana",
    })).json()["id"]

    a = await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Alumno A", "campus_id": campus_a,
    })
    assert a.status_code == 201, a.text
    b = await client.post("/api/v1/students", json={
        "curp": CURP_B, "full_name": "Alumno B", "campus_id": campus_b,
    })
    assert b.status_code == 201, b.text

    # a servicios_escolares member with membership ONLY to campus A
    member = (await client.post("/api/v1/users", json={
        "email": "member@inue.edu.mx", "full_name": "Member A",
        "role": "servicios_escolares", "password": "memberpass1",
        "campuses": [campus_a],
    })).json()
    assert member["campuses"] == [campus_a]
    assert member["all_campuses"] is False

    # switch to the member
    resp = await client.post("/api/v1/auth/login", data={
        "username": "member@inue.edu.mx", "password": "memberpass1",
    })
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["campuses"] == [campus_a] and me["all_campuses"] is False

    # list: only campus A's student, campus B's is invisible
    students = (await client.get("/api/v1/students")).json()
    curps = {s["curp"] for s in students}
    assert CURP_A in curps and CURP_B not in curps

    # explicit ?campus_id to a foreign campus → 403
    denied = await client.get(f"/api/v1/students?campus_id={campus_b}")
    assert denied.status_code == 403

    # X-Campus header naming a foreign campus → 403
    denied_hdr = await client.get("/api/v1/students", headers={"X-Campus": campus_b})
    assert denied_hdr.status_code == 403

    # create in a foreign campus → 403 (pinned/validated to membership)
    denied_create = await client.post("/api/v1/students", json={
        "curp": "PERJ030303HBCXNS01", "full_name": "Nope", "campus_id": campus_b,
    })
    assert denied_create.status_code == 403

    # create in own campus → allowed
    ok_create = await client.post("/api/v1/students", json={
        "curp": "LOPM040404MBCXNS02", "full_name": "Sí", "campus_id": campus_a,
    })
    assert ok_create.status_code == 201, ok_create.text


async def test_all_campus_sees_everything(client, seed):
    """Superuser (all-campus) is unrestricted across campuses."""
    await login(client)
    campus_a = str(seed["campus"].id)
    campus_b = (await client.post("/api/v1/catalog/campuses", json={
        "name": "Campus Tijuana",
    })).json()["id"]
    await client.post("/api/v1/students", json={
        "curp": CURP_A, "full_name": "Alumno A", "campus_id": campus_a,
    })
    await client.post("/api/v1/students", json={
        "curp": CURP_B, "full_name": "Alumno B", "campus_id": campus_b,
    })
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["all_campuses"] is True
    assert set(me["campuses"]) == {campus_a, campus_b}

    students = (await client.get("/api/v1/students")).json()
    curps = {s["curp"] for s in students}
    assert CURP_A in curps and CURP_B in curps


async def test_groups_and_rvoes_scoped(client, seed):
    """Groups/RVOEs are campus-tier: a member only sees their campus'."""
    await login(client)
    campus_a = str(seed["campus"].id)
    campus_b = (await client.post("/api/v1/catalog/campuses", json={
        "name": "Campus Tijuana",
    })).json()["id"]
    _, rvoe_a = await _make_program_rvoe(client, campus_a, code="AA", agreement="A0001")
    _, rvoe_b = await _make_program_rvoe(client, campus_b, code="BB", agreement="B0001")
    plan_a = (await client.post("/api/v1/catalog/plan-versions", json={
        "rvoe_id": rvoe_a["id"], "version_label": "2026",
    })).json()
    plan_b = (await client.post("/api/v1/catalog/plan-versions", json={
        "rvoe_id": rvoe_b["id"], "version_label": "2026",
    })).json()
    term = (await client.post("/api/v1/catalog/terms", json={
        "name": "2026-2", "period_type": "cuatrimestral",
        "start_date": "2026-09-01", "end_date": "2026-12-15",
    })).json()
    for plan, code in ((plan_a, "AA-1A"), (plan_b, "BB-1A")):
        r = await client.post("/api/v1/catalog/groups", json={
            "code": code, "period_number": 1, "plan_version_id": plan["id"],
            "term_id": term["id"],
        })
        assert r.status_code == 201, r.text

    # member of campus A only
    await client.post("/api/v1/users", json={
        "email": "member@inue.edu.mx", "full_name": "Member A",
        "role": "coordinador_academico", "password": "memberpass1",
        "campuses": [campus_a],
    })
    await login(client, "member@inue.edu.mx", password="memberpass1")

    groups = (await client.get("/api/v1/catalog/groups")).json()
    assert {g["code"] for g in groups} == {"AA-1A"}
    assert all(g["campus_id"] == campus_a for g in groups)

    rvoes = (await client.get("/api/v1/catalog/rvoes")).json()
    assert {r["campus_id"] for r in rvoes} == {campus_a}

    # creating a group whose RVOE lives in campus B → 403
    denied = await client.post("/api/v1/catalog/groups", json={
        "code": "BB-2A", "period_number": 1, "plan_version_id": plan_b["id"],
        "term_id": term["id"],
    })
    assert denied.status_code == 403


async def test_update_user_campuses_replaces_membership(client, seed):
    """Admin can rewrite a user's membership; /me reflects it immediately."""
    await login(client)
    campus_a = str(seed["campus"].id)
    campus_b = (await client.post("/api/v1/catalog/campuses", json={
        "name": "Campus Tijuana",
    })).json()["id"]
    user = (await client.post("/api/v1/users", json={
        "email": "member@inue.edu.mx", "full_name": "Member",
        "role": "servicios_escolares", "password": "memberpass1",
        "campuses": [campus_a],
    })).json()
    updated = (await client.patch(f"/api/v1/users/{user['id']}", json={
        "campuses": [campus_b],
    })).json()
    assert updated["campuses"] == [campus_b]

    await login(client, "member@inue.edu.mx", password="memberpass1")
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["campuses"] == [campus_b]
