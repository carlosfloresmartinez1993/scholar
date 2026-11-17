"""Sincronización de planteles y carreras con el calendario (cliente simulado)."""
import uuid

from tests.conftest import login

API = "/api/v1/catalog"
CAMPUS_A = {"id": str(uuid.uuid4()), "code": "inue_presencial", "name": "INUE Presencial",
            "is_active": True, "modality": "escolarizada"}
CAMPUS_B = {"id": str(uuid.uuid4()), "code": "inue_online", "name": "INUE Online",
            "is_active": True, "modality": "no_escolarizada"}


def program(name, rvoe, campus=CAMPUS_A, level="licenciatura"):
    return {"id": str(uuid.uuid4()), "name": name, "rvoe": rvoe, "campus": campus["code"],
            "campus_id": campus["id"], "level": level}


def fake(monkeypatch, campuses, programs=()):
    async def get_campuses():
        return [dict(c) for c in campuses]

    async def get_programs():
        return [dict(p) for p in programs]
    monkeypatch.setattr("app.services.calendar.get_campuses", get_campuses)
    monkeypatch.setattr("app.services.calendar.get_programs", get_programs)


async def test_sync_campuses_creates_links_and_keeps_local_edits(client, seed, monkeypatch):
    await login(client)
    # the seed campus has the same name as one of the calendar: it is linked, not duplicated
    same_name = dict(CAMPUS_A, name=seed["campus"].name.upper())
    fake(monkeypatch, [same_name, CAMPUS_B])

    result = (await client.post(f"{API}/campuses/sync-calendar")).json()
    assert result["linked"] == [seed["campus"].name]
    assert result["created"] == ["INUE Online"]
    campuses = (await client.get(f"{API}/campuses")).json()
    assert len(campuses) == 2
    online = next(c for c in campuses if c["name"] == "INUE Online")
    assert online["calendar_campus_id"] == CAMPUS_B["id"]

    # edited here: the next sync reports the difference and leaves it alone
    edited = await client.patch(f"{API}/campuses/{online['id']}",
                                json={"name": "INUE En Línea", "address": "Av. Siempre Viva 1"})
    assert edited.status_code == 200, edited.text
    again = (await client.post(f"{API}/campuses/sync-calendar")).json()
    assert again["created"] == [] and again["linked"] == []
    assert {"scholar": "INUE En Línea", "calendar": "INUE Online"} in again["different"]
    campuses = (await client.get(f"{API}/campuses")).json()
    assert {c["name"] for c in campuses} == {seed["campus"].name, "INUE En Línea"}

    # a campus added by hand in scholar stays, with no link
    own = await client.post(f"{API}/campuses", json={"name": "Plantel Nuevo"})
    assert own.status_code == 201
    assert own.json()["calendar_campus_id"] is None
    assert (await client.patch(f"{API}/campuses/{own.json()['id']}", json={"name": "  "})).status_code == 422


async def test_import_programs_from_calendar(client, seed, monkeypatch):
    await login(client)
    derecho = program("DERECHO", "RVOE-BC-011-M3/13")
    conta = program("CONTADURÍA", None)
    bach = program("Diplomado ONLINE", "RVOE-MS-003", CAMPUS_B, "diplomado")
    fake(monkeypatch, [CAMPUS_A, CAMPUS_B], [derecho, conta, bach])

    # a program captured by hand with the same name is linked, not duplicated
    own = (await client.post(f"{API}/programs", json={
        "code": "CONTA", "name": "Contaduría", "level": "licenciatura"})).json()

    # the campus is not synced yet: nothing new can come in
    before = {r["name"]: r for r in (await client.get(f"{API}/calendar/programs/preview")).json()}
    assert before["DERECHO"]["status"] == "no_importable"
    assert "plantel" in before["DERECHO"]["problems"][0]

    await client.post(f"{API}/campuses/sync-calendar")
    preview = {r["name"]: r for r in (await client.get(f"{API}/calendar/programs/preview")).json()}
    assert preview["DERECHO"]["status"] == "nueva"
    assert preview["DERECHO"]["rvoe"] == "RVOE-BC-011-M3/13" and preview["DERECHO"]["has_rvoe"] is False
    assert preview["CONTADURÍA"]["status"] == "vincular"
    assert preview["CONTADURÍA"]["rvoe"] is None
    assert preview["Diplomado ONLINE"]["status"] == "no_importable"
    assert "diplomado" in preview["Diplomado ONLINE"]["problems"][0]

    result = await client.post(f"{API}/programs/import-calendar", json={
        "calendar_program_ids": [derecho["id"], conta["id"], bach["id"]]})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["created"] == ["DERECHO"]
    assert body["linked"] == ["CONTADURÍA"]
    assert [s["name"] for s in body["skipped"]] == ["Diplomado ONLINE"]

    programs = {p["name"]: p for p in (await client.get(f"{API}/programs")).json()}
    assert programs["DERECHO"]["calendar_program_id"] == derecho["id"]
    assert programs["DERECHO"]["code"] == "DERECHO"
    assert programs["Contaduría"]["id"] == own["id"]  # the local name is kept
    assert programs["Contaduría"]["calendar_program_id"] == conta["id"]
    assert "Diplomado ONLINE" not in programs
    # the RVOE is not invented: its date and authority are captured in scholar
    assert (await client.get(f"{API}/rvoes")).json() == []

    after = {r["name"]: r for r in (await client.get(f"{API}/calendar/programs/preview")).json()}
    assert after["DERECHO"]["status"] == "sincronizada"
    assert after["CONTADURÍA"]["status"] == "diferente"  # «Contaduría» here
    again = (await client.post(f"{API}/programs/import-calendar", json={
        "calendar_program_ids": [derecho["id"]]})).json()
    assert again["created"] == [] and again["skipped"][0]["reason"] == "ya sincronizada"
    empty = await client.post(f"{API}/programs/import-calendar", json={"calendar_program_ids": []})
    assert empty.status_code == 400
