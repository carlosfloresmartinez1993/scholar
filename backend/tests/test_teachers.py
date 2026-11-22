"""Profesores: Servicios Escolares creates a docente (account + expediente, access
by email), edits them, and sees their classes once assigned in Grupos."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog

API = "/api/v1"


async def test_create_edit_and_see_classes(client, seed, monkeypatch):
    sent = []
    monkeypatch.setattr("app.api.routes.teachers.send_email", lambda **kw: sent.append(kw))
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)

    created = await client.post(f"{API}/teachers", json={
        "full_name": "Laura Méndez", "email": "Laura.Mendez@inue.edu.mx",
        "campus_ids": [campus_id], "cedula_profesional": "1234567",
        "max_degree": "Maestría en Derecho"})
    assert created.status_code == 201, created.text
    teacher = created.json()
    assert (teacher["email"], teacher["max_degree"]) == ("laura.mendez@inue.edu.mx", "Maestría en Derecho")
    assert [c["id"] for c in teacher["campuses"]] == [campus_id]
    assert sent and sent[0]["to"] == "laura.mendez@inue.edu.mx" and "Contraseña" in sent[0]["html"]
    assert "password" not in created.text
    assert (await client.post(f"{API}/teachers", json={
        "full_name": "Otra", "email": "laura.mendez@inue.edu.mx"})).status_code == 409

    # assigned to a materia in Grupos: it shows in their ficha and the count
    gs = (await client.get(f"{API}/catalog/groups/{catalog['group']['id']}/subjects")).json()[0]
    assigned = await client.patch(f"{API}/catalog/group-subjects/{gs['id']}", json={
        "group_id": gs["group_id"], "plan_subject_id": gs["plan_subject_id"],
        "teacher_user_id": teacher["id"]})
    assert assigned.status_code == 200, assigned.text
    listed = {t["id"]: t for t in (await client.get(f"{API}/teachers")).json()}
    assert listed[teacher["id"]]["classes_now"] == 1
    ficha = (await client.get(f"{API}/teachers/{teacher['id']}")).json()
    assert [c["group_code"] for c in ficha["classes"]] == ["LD-1A"]

    edited = await client.patch(f"{API}/teachers/{teacher['id']}", json={
        "max_degree": "Doctorado en Derecho", "is_active": False, "campus_ids": []})
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["max_degree"], body["is_active"], body["campuses"]) == ("Doctorado en Derecho", False, [])

    # only docentes are profesores
    staff = (await client.get(f"{API}/users")).json()[0]
    assert (await client.get(f"{API}/teachers/{staff['id']}")).status_code == 404
