"""Todo el catálogo se edita desde Scholar: niveles, carreras, planes, grupos, y
la importación de grupos del calendario (cliente simulado)."""
import uuid

from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_student_kardex import enroll_student

API = "/api/v1/catalog"


async def test_education_levels_are_an_editable_catalog(client, seed):
    await login(client)
    levels = {lv["code"]: lv for lv in (await client.get(f"{API}/education-levels")).json()}
    assert {"preescolar", "primaria", "bachillerato", "licenciatura", "doctorado"} <= set(levels)

    created = await client.post(f"{API}/education-levels", json={
        "code": "Diplomado", "name": "Diplomado", "sort_order": 95})
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "diplomado"
    assert (await client.post(f"{API}/education-levels", json={
        "code": "diplomado", "name": "Otro"})).status_code == 409

    program = await client.post(f"{API}/programs", json={
        "code": "DIP-1", "name": "Diplomado en Docencia", "level": "diplomado"})
    assert program.status_code == 201, program.text
    assert (await client.post(f"{API}/programs", json={
        "code": "X", "name": "X", "level": "inexistente"})).status_code == 422

    level_id = created.json()["id"]
    renamed = await client.patch(f"{API}/education-levels/{level_id}", json={"name": "Diplomados"})
    assert renamed.json()["name"] == "Diplomados"
    # in use: it can be deactivated, not deleted
    assert (await client.delete(f"{API}/education-levels/{level_id}")).status_code == 409
    await client.patch(f"{API}/education-levels/{level_id}", json={"is_active": False})
    active = {lv["code"] for lv in (await client.get(f"{API}/education-levels")).json()}
    assert "diplomado" not in active
    every = {lv["code"] for lv in (await client.get(f"{API}/education-levels?include_inactive=true")).json()}
    assert "diplomado" in every
    unused = levels["preescolar"]["id"]
    assert (await client.delete(f"{API}/education-levels/{unused}")).status_code == 204


async def test_program_and_plan_can_be_edited(client, seed):
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))
    program_id = catalog["program"]["id"]
    edited = await client.patch(f"{API}/programs/{program_id}", json={
        "code": "LD-2026", "name": "Licenciatura en Derecho (2026)", "level": "maestria",
        "is_active": False})
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["code"], body["name"], body["level"], body["is_active"]) == (
        "LD-2026", "Licenciatura en Derecho (2026)", "maestria", False)
    other = (await client.post(f"{API}/programs", json={
        "code": "PSI", "name": "Psicología", "level": "licenciatura"})).json()
    assert (await client.patch(f"{API}/programs/{other['id']}", json={"code": "LD-2026"})).status_code == 409

    plan_id = catalog["plan"]["id"]
    plan = await client.patch(f"{API}/plan-versions/{plan_id}", json={
        "version_label": "2026-A", "periods_count": 8, "min_attendance_pct": 75})
    assert plan.status_code == 200, plan.text
    assert (plan.json()["version_label"], plan.json()["periods_count"]) == ("2026-A", 8)
    # subjects reach the 2nd period: the plan can't be shorter
    assert (await client.patch(f"{API}/plan-versions/{plan_id}", json={"periods_count": 1})).status_code == 409


async def test_group_edit_and_delete(client, seed):
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))
    group_id = catalog["group"]["id"]
    # empty: its cuatrimestre can change, and it takes that period's subjects
    moved = await client.patch(f"{API}/groups/{group_id}", json={"code": "LD-2Z", "period_number": 2})
    assert moved.status_code == 200, moved.text
    subjects = (await client.get(f"{API}/groups/{group_id}/subjects")).json()
    assert [s["plan_subject_id"] for s in subjects] == [catalog["subject_b"]["id"]]
    assert (await client.patch(f"{API}/groups/{group_id}", json={"period_number": 30})).status_code == 422

    spare = (await client.post(f"{API}/groups", json={
        "code": "LD-1X", "period_number": 1, "plan_version_id": catalog["plan"]["id"],
        "term_id": catalog["term"]["id"]})).json()
    assert (await client.patch(f"{API}/groups/{spare['id']}", json={"code": "LD-2Z"})).status_code == 409
    assert (await client.delete(f"{API}/groups/{spare['id']}")).status_code == 204
    assert (await client.get(f"{API}/groups/{spare['id']}")).status_code == 404

    # with students: no cuatrimestre change, no delete — it is deactivated
    await client.patch(f"{API}/groups/{group_id}", json={"period_number": 1})
    await enroll_student(client, str(seed["campus"].id), group_id)
    assert (await client.patch(f"{API}/groups/{group_id}", json={"period_number": 2})).status_code == 409
    assert (await client.delete(f"{API}/groups/{group_id}")).status_code == 409
    off = await client.patch(f"{API}/groups/{group_id}", json={"is_active": False, "code": "LD-1A-T"})
    assert off.status_code == 200 and off.json()["is_active"] is False


async def test_import_groups_of_a_term_from_calendar(client, seed, monkeypatch, session_factory):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    cal_campus, cal_program, cal_other = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    cal_term = str(uuid.uuid4())
    groups = [
        {"id": str(uuid.uuid4()), "code": "DE21S", "program_id": cal_program, "term_id": cal_term,
         "campus": "inue_presencial", "campus_id": cal_campus},
        {"id": str(uuid.uuid4()), "code": "TCM1", "program_id": cal_program, "term_id": cal_term,
         "campus": "inue_presencial", "campus_id": cal_campus},
        {"id": str(uuid.uuid4()), "code": "PSI31", "program_id": cal_other, "term_id": cal_term,
         "campus": "inue_presencial", "campus_id": cal_campus},
    ]

    async def get_groups(term_id=None, program_id=None):
        return [dict(g) for g in groups]
    monkeypatch.setattr("app.services.calendar.get_groups", get_groups)

    term_id = catalog["term"]["id"]
    not_linked = await client.get(f"{API}/terms/{term_id}/calendar-groups/preview")
    assert not_linked.status_code == 409

    # link term, campus and program as an import would have
    from sqlmodel import select

    from app.models import Campus, Program, Term
    async with session_factory() as session:
        (await session.get(Term, uuid.UUID(term_id))).calendar_term_id = uuid.UUID(cal_term)
        (await session.get(Campus, seed["campus"].id)).calendar_campus_id = uuid.UUID(cal_campus)
        program = (await session.exec(select(Program).where(Program.id == uuid.UUID(catalog["program"]["id"])))).one()
        program.calendar_program_id = uuid.UUID(cal_program)
        await session.commit()

    preview = (await client.get(f"{API}/terms/{term_id}/calendar-groups/preview")).json()
    rows = {r["code"]: r for r in preview["groups"]}
    assert rows["DE21S"]["status"] == "nuevo" and rows["DE21S"]["suggested_period"] == 2
    assert rows["DE21S"]["plans"][0]["plan_version_id"] == catalog["plan"]["id"]
    assert rows["TCM1"]["suggested_period"] == 1
    assert rows["PSI31"]["status"] == "sin_carrera"

    result = await client.post(f"{API}/terms/{term_id}/calendar-groups/import", json={"items": [
        {"calendar_group_id": rows["DE21S"]["calendar_group_id"], "plan_version_id": catalog["plan"]["id"],
         "period_number": 2, "code": "DE21S"},
        {"calendar_group_id": rows["TCM1"]["calendar_group_id"], "plan_version_id": catalog["plan"]["id"],
         "period_number": 1, "code": "LD-1A"},  # code taken in the term: skipped
    ]})
    assert result.status_code == 200, result.text
    assert result.json()["created"] == ["DE21S"]
    assert result.json()["skipped"][0]["code"] == "LD-1A"

    created = next(g for g in (await client.get(f"{API}/groups?term_id={term_id}")).json() if g["code"] == "DE21S")
    assert created["calendar_group_id"] == rows["DE21S"]["calendar_group_id"]
    assert created["period_number"] == 2
    subjects = (await client.get(f"{API}/groups/{created['id']}/subjects")).json()
    assert [s["plan_subject_id"] for s in subjects] == [catalog["subject_b"]["id"]]

    again = {r["code"]: r for r in (await client.get(f"{API}/terms/{term_id}/calendar-groups/preview")).json()["groups"]}
    assert again["DE21S"]["status"] == "importado"
