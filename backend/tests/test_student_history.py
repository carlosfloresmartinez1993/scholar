"""Historia del alumno: ingreso, cuatrimestres, baja, reingreso and corrections, in
order, plus where the student is now."""
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student

API = "/api/v1"


async def test_history_tells_what_happened(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await enroll_student(client, campus_id, catalog["group"]["id"])
    ses = (await client.get(f"{API}/students/{student['id']}/subject-enrollments")).json()
    await client.post(f"{API}/grades/subject-enrollments/{ses[0]['id']}/correct",
                      json={"final_grade": 9, "reason": "acta de ordinario"})

    # leaves, and comes back the next cuatrimestre into 2.º
    await client.patch(f"{API}/students/{student['id']}", json={"status": "baja_temporal"})
    term2 = (await client.post(f"{API}/catalog/terms", json={
        "name": "2027-1 ENE-ABR", "period_type": "cuatrimestral",
        "start_date": "2027-01-11", "end_date": "2027-04-30"})).json()
    group2 = (await client.post(f"{API}/catalog/groups", json={
        "code": "LD-2A", "period_number": 2, "plan_version_id": catalog["plan"]["id"],
        "term_id": term2["id"]})).json()
    await client.patch(f"{API}/students/{student['id']}", json={"status": "activo"})
    enrolled = await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group2["id"]})
    assert enrolled.status_code == 201, enrolled.text

    history = (await client.get(f"{API}/students/{student['id']}/history")).json()
    kinds = [e["kind"] for e in history["events"]]
    assert kinds[0] == "ingreso"
    assert {"correccion", "baja", "estatus", "reingreso"} <= set(kinds)
    assert kinds.index("baja") < kinds.index("reingreso")
    ingreso = history["events"][0]
    assert "Licenciatura en Derecho" in ingreso["title"] and "LD-1A" in ingreso["title"]
    assert "1 aprobada" in ingreso["detail"]
    reingreso = next(e for e in history["events"] if e["kind"] == "reingreso")
    assert "2.º" in reingreso["title"] and reingreso["term"] == "2027-1 ENE-ABR"
    correction = next(e for e in history["events"] if e["kind"] == "correccion")
    assert "sin calificación → 9" in correction["detail"]
    assert "motivo: acta de ordinario" in correction["detail"]

    assert history["current"]["group_code"] == "LD-2A"
    assert history["current"]["period_number"] == 2
    assert history["status_label"] == "Activo"
