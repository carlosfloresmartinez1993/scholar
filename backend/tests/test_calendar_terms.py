"""Phase 7: terms imported from the calendar system (source of truth for periods).
The calendar client is monkeypatched — no live calendar in tests."""
import uuid

from tests.conftest import login

CAL_TERM = {
    "id": str(uuid.uuid4()),
    "code": "2026-42",
    "name": "Cuatrimestre Mayo-Agosto 2026",
    "year": 2026,
    "start_date": "2026-05-04",
    "end_date": "2026-08-21",
    "is_active": True,
}


async def test_import_term_from_calendar(client, seed, monkeypatch):
    await login(client)

    async def fake_get_terms():
        return [dict(CAL_TERM)]
    monkeypatch.setattr("app.services.calendar.get_terms", fake_get_terms)

    listed = (await client.get("/api/v1/catalog/calendar/terms")).json()
    assert listed[0]["imported"] is False

    res = await client.post(
        "/api/v1/catalog/terms/import", json={"calendar_term_id": CAL_TERM["id"]}
    )
    assert res.status_code == 201, res.text
    term = res.json()
    assert term["start_date"] == "2026-05-04"  # dates come from the calendar
    assert term["end_date"] == "2026-08-21"
    assert term["calendar_term_id"] == CAL_TERM["id"]

    listed2 = (await client.get("/api/v1/catalog/calendar/terms")).json()
    assert listed2[0]["imported"] is True  # now flagged as imported
    dup = await client.post(
        "/api/v1/catalog/terms/import", json={"calendar_term_id": CAL_TERM["id"]}
    )
    assert dup.status_code == 409  # not imported twice


async def test_sync_term_dates_from_calendar(client, seed, monkeypatch):
    await login(client)

    async def fake_get_terms():
        return [dict(CAL_TERM)]
    monkeypatch.setattr("app.services.calendar.get_terms", fake_get_terms)
    term = (await client.post(
        "/api/v1/catalog/terms/import", json={"calendar_term_id": CAL_TERM["id"]}
    )).json()

    # the calendar moves the end date → sync pulls the new one
    async def fake_get_terms_moved():
        return [{**CAL_TERM, "end_date": "2026-08-28"}]
    monkeypatch.setattr("app.services.calendar.get_terms", fake_get_terms_moved)
    synced = (await client.post(
        f"/api/v1/catalog/terms/{term['id']}/sync-calendar"
    )).json()
    assert synced["end_date"] == "2026-08-28"


async def test_import_rejects_undated_calendar_term(client, seed, monkeypatch):
    await login(client)

    async def fake_get_terms():
        return [{**CAL_TERM, "start_date": None, "end_date": None}]
    monkeypatch.setattr("app.services.calendar.get_terms", fake_get_terms)
    res = await client.post(
        "/api/v1/catalog/terms/import", json={"calendar_term_id": CAL_TERM["id"]}
    )
    assert res.status_code == 422  # can't build payment dates without term dates


async def test_import_rejects_malformed_calendar_dates(client, seed, monkeypatch):
    await login(client)

    async def fake_get_terms():
        return [{**CAL_TERM, "start_date": "not-a-date"}]
    monkeypatch.setattr("app.services.calendar.get_terms", fake_get_terms)
    res = await client.post(
        "/api/v1/catalog/terms/import", json={"calendar_term_id": CAL_TERM["id"]}
    )
    assert res.status_code == 422  # malformed calendar date → controlled 422, not 500
