"""Alumno de baja (temporal o definitiva): sale como baja en la lista de asistencia y
no se le pasa lista; el maestro ve el estatus al capturar (y puede capturar); no se
promueve al siguiente ciclo; no puede entrar al sistema. Su historial se queda."""
from datetime import date, timedelta

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import login
from tests.test_academic_flow import CURP_A, CURP_B, build_catalog
from tests.test_portal import capture_emails, make_enrolled_student, password_from
from tests.test_treasury_documents import make_student

API = "/api/v1"


async def test_attendance_and_capture_show_the_baja(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    active = await make_student(client, campus_id, curp=CURP_A)
    away = await make_student(client, campus_id, curp=CURP_B)
    for s in (active, away):
        await client.post(f"{API}/students/group-enrollments", json={
            "student_id": s["id"], "group_id": catalog["group"]["id"]})
    gs = (await client.get(f"{API}/catalog/groups/{catalog['group']['id']}/subjects")).json()[0]

    changed = await client.patch(f"{API}/students/{away['id']}", json={"status": "baja_temporal"})
    assert changed.status_code == 200, changed.text

    grid = {r["student_id"]: r for r in (await client.get(
        f"{API}/grades/group-subjects/{gs['id']}/grid")).json()["rows"]}
    # still in the list (the grade can be captured), with their status
    assert grid[away["id"]]["student_status"] == "baja_temporal"
    assert grid[active["id"]]["student_status"] == "activo"

    roll = {"group_subject_id": gs["id"], "session_date": "2026-09-10", "sequence": 1}
    refused = await client.post(f"{API}/attendance/sessions", json={**roll, "records": [
        {"student_id": active["id"], "status": "presente"},
        {"student_id": away["id"], "status": "presente"}]})
    assert refused.status_code == 409 and "baja" in refused.json()["detail"]
    ok = await client.post(f"{API}/attendance/sessions", json={**roll, "records": [
        {"student_id": active["id"], "status": "presente"}]})
    assert ok.status_code == 201, ok.text

    report = {r["student_id"]: r for r in (await client.get(
        f"{API}/attendance/group-subjects/{gs['id']}/report")).json()}
    assert report[away["id"]]["student_status"] == "baja_temporal"


async def test_a_student_de_baja_is_not_promoted(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    term1, group1 = catalog["term"], catalog["group"]
    comp = (await client.post(f"{API}/catalog/evaluation-components", json={
        "plan_subject_id": catalog["subject_a"]["id"], "kind": "ordinario",
        "label": "Ordinario", "weight_pct": 100, "sequence": 1})).json()
    await client.patch(f"{API}/catalog/terms/{term1['id']}", json={"grade_capture_open": True})
    stays, leaves = (await make_student(client, campus_id, curp=CURP_A),
                     await make_student(client, campus_id, curp=CURP_B))
    for s in (stays, leaves):
        await client.post(f"{API}/students/group-enrollments", json={
            "student_id": s["id"], "group_id": group1["id"]})
        ses = (await client.get(f"{API}/students/{s['id']}/subject-enrollments")).json()
        await client.post(f"{API}/grades/capture-batch", json=[
            {"subject_enrollment_id": ses[0]["id"], "component_id": comp["id"], "value": 9}])
    # passed the cuatrimestre and then left
    await client.patch(f"{API}/students/{leaves['id']}", json={"status": "baja_definitiva"})

    today = date.today()
    term2 = (await client.post(f"{API}/catalog/terms", json={
        "name": "2027-1 ENE-ABR", "period_type": "cuatrimestral",
        "start_date": (today + timedelta(days=5)).isoformat(),
        "end_date": (today + timedelta(days=120)).isoformat()})).json()
    await client.post(f"{API}/catalog/groups", json={
        "code": "LD-2A", "period_number": 2, "plan_version_id": catalog["plan"]["id"],
        "term_id": term2["id"], "promotes_from_group_id": group1["id"]})

    preview = (await client.post(f"{API}/students/promote-cycle?dry_run=true")).json()
    assert {p["matricula"] for p in preview["promoted"]} == {stays["enrollment_number"]}
    assert any(s["matricula"] == leaves["enrollment_number"] and "de baja definitiva" in s["reason"]
               for s in preview["skipped"])
    # their history stays: the passed subject is in the kárdex
    kardex = (await client.get(f"{API}/grades/students/{leaves['id']}/kardex-completo")).json()
    row = next(r for r in kardex["rows"] if r["plan_subject_id"] == catalog["subject_a"]["id"])
    assert row["status"] == "aprobada"


async def test_a_student_de_baja_cannot_get_in(client, seed, monkeypatch):
    await login(client)
    sent = capture_emails(monkeypatch)
    student = await make_enrolled_student(client, seed)
    assert (await client.post(f"{API}/students/{student['id']}/portal-access")).status_code == 201
    password = password_from(sent)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as portal:
        first = await portal.post(f"{API}/auth/login",
                                  data={"username": "rosa@test.mx", "password": password})
        assert first.status_code == 200, first.text
        assert (await portal.get(f"{API}/portal/me")).status_code == 200

        await client.patch(f"{API}/students/{student['id']}", json={"status": "baja_temporal"})
        # the open session ends, and a new login says why
        kicked = await portal.get(f"{API}/portal/me")
        assert kicked.status_code == 403 and "dado de baja" in kicked.json()["detail"]
        again = await portal.post(f"{API}/auth/login",
                                  data={"username": "rosa@test.mx", "password": password})
        assert again.status_code == 403 and "dado de baja" in again.json()["detail"]

        # back as activo: in again
        await client.patch(f"{API}/students/{student['id']}", json={"status": "activo"})
        back = await portal.post(f"{API}/auth/login",
                                 data={"username": "rosa@test.mx", "password": password})
        assert back.status_code == 200
