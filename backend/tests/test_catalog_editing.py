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


async def test_new_program_visible_with_a_campus_chosen(client, seed):
    """With a campus chosen in the header, a program without RVOE still shows."""
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))
    other = (await client.post(f"{API}/campuses", json={"name": "Otro plantel"})).json()
    new = (await client.post(f"{API}/programs", json={
        "code": "BACH", "name": "Bachillerato", "level": "bachillerato"})).json()
    here = {p["code"] for p in (await client.get(
        f"{API}/programs", headers={"X-Campus": str(seed["campus"].id)})).json()}
    assert {"LD", "BACH"} <= here
    there = {p["code"] for p in (await client.get(
        f"{API}/programs", headers={"X-Campus": other["id"]})).json()}
    assert "BACH" in there and "LD" not in there  # LD's RVOE is in the other campus
    assert new["code"] == "BACH" and catalog


async def test_campus_filter_does_not_block_creating_elsewhere(client, seed):
    """The header campus only filters the view: an admin looking at one campus can
    create a RVOE in another."""
    await login(client)
    online = (await client.post(f"{API}/campuses", json={"name": "INUE Online"})).json()
    program = (await client.post(f"{API}/programs", json={
        "code": "BACH", "name": "Bachillerato", "level": "bachillerato"})).json()
    created = await client.post(f"{API}/rvoes", headers={"X-Campus": str(seed["campus"].id)}, json={
        "program_id": program["id"], "campus_id": online["id"], "agreement_number": "2023313/22",
        "authority": "estatal", "modality": "escolarizada", "issue_date": "2026-11-16"})
    assert created.status_code == 201, created.text


async def test_one_rvoe_in_several_campuses(client, seed):
    """Opción A: el mismo RVOE (mismo plan) se imparte en varios planteles; cada
    grupo es de uno de ellos y el alumno queda en el plantel de su grupo."""
    await login(client)
    main = str(seed["campus"].id)
    catalog = await build_catalog(client, main)
    online = (await client.post(f"{API}/campuses", json={"name": "INUE Online"})).json()["id"]
    elsewhere = (await client.post(f"{API}/campuses", json={"name": "Ensenada"})).json()["id"]
    rvoe_id = catalog["rvoe"]["id"]

    shared = await client.patch(f"{API}/rvoes/{rvoe_id}", json={"extra_campus_ids": [online]})
    assert shared.status_code == 200, shared.text
    assert shared.json()["campus_ids"] == [main, online]

    # the program shows in both campuses, with its RVOE and planteles
    there = {p["code"]: p for p in (await client.get(f"{API}/programs", headers={"X-Campus": online})).json()}
    assert there["LD"]["rvoes"][0]["campus_ids"] == [main, online]
    assert "LD" not in {p["code"] for p in (await client.get(
        f"{API}/programs", headers={"X-Campus": elsewhere})).json()}
    assert [r["id"] for r in (await client.get(f"{API}/rvoes", headers={"X-Campus": online})).json()] == [rvoe_id]

    base = {"period_number": 1, "plan_version_id": catalog["plan"]["id"], "term_id": catalog["term"]["id"]}
    group = await client.post(f"{API}/groups", json={**base, "code": "LD-1ON", "campus_id": online})
    assert group.status_code == 201, group.text
    assert group.json()["campus_id"] == online
    assert (await client.post(f"{API}/groups", json={
        **base, "code": "LD-1EN", "campus_id": elsewhere})).status_code == 422

    student = await enroll_student(client, online, group.json()["id"])
    assert student["campus_id"] == online

    # Online has groups of this RVOE now: it can't be taken off
    assert (await client.patch(f"{API}/rvoes/{rvoe_id}", json={"extra_campus_ids": []})).status_code == 409


async def test_same_group_code_in_two_campuses(client, seed, monkeypatch, session_factory):
    """Bachillerato con un RVOE en SISCOM y otro en Online: cada plantel tiene su
    «B1», y el grupo del calendario queda en su plantel, no en el del otro RVOE."""
    await login(client)
    catalog = await build_catalog(client, str(seed["campus"].id))
    siscom = (await client.post(f"{API}/campuses", json={"name": "Instituto SISCOM"})).json()["id"]
    online = (await client.post(f"{API}/campuses", json={"name": "INUE Online"})).json()["id"]
    program = (await client.post(f"{API}/programs", json={
        "code": "BACH", "name": "Bachillerato", "level": "bachillerato"})).json()
    plans = {}
    for campus, number in [(siscom, "BACH-SISCOM"), (online, "BACH-ONLINE")]:
        rvoe = (await client.post(f"{API}/rvoes", json={
            "program_id": program["id"], "campus_id": campus, "agreement_number": number,
            "authority": "estatal", "modality": "escolarizada", "issue_date": "2026-01-15"})).json()
        plans[campus] = (await client.post(f"{API}/plan-versions", json={
            "rvoe_id": rvoe["id"], "version_label": "2026", "period_type": "cuatrimestral",
            "periods_count": 6, "min_attendance_pct": 80})).json()["id"]
    term_id = catalog["term"]["id"]
    for campus in (siscom, online):
        made = await client.post(f"{API}/groups", json={
            "code": "B1", "period_number": 1, "plan_version_id": plans[campus],
            "term_id": term_id, "campus_id": campus})
        assert made.status_code == 201, made.text
        assert made.json()["campus_id"] == campus
    # a plan of SISCOM can't open a group in Online
    assert (await client.post(f"{API}/groups", json={
        "code": "B2", "period_number": 1, "plan_version_id": plans[siscom],
        "term_id": term_id, "campus_id": online})).status_code == 422

    # calendar: B4 is Online's; only Online's plan is offered, SISCOM's is refused
    cal_term, cal_program, cal_online = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    cal_group = {"id": str(uuid.uuid4()), "code": "B41", "program_id": cal_program,
                 "term_id": cal_term, "campus_id": cal_online}

    async def get_groups(term_id=None, program_id=None):
        return [dict(cal_group)]
    monkeypatch.setattr("app.services.calendar.get_groups", get_groups)
    from app.models import Campus, Program, Term
    async with session_factory() as session:
        (await session.get(Term, uuid.UUID(term_id))).calendar_term_id = uuid.UUID(cal_term)
        (await session.get(Campus, uuid.UUID(online))).calendar_campus_id = uuid.UUID(cal_online)
        (await session.get(Program, uuid.UUID(program["id"]))).calendar_program_id = uuid.UUID(cal_program)
        await session.commit()

    row = (await client.get(f"{API}/terms/{term_id}/calendar-groups/preview")).json()["groups"][0]
    assert [p["plan_version_id"] for p in row["plans"]] == [plans[online]]
    item = {"calendar_group_id": cal_group["id"], "period_number": 4, "code": "B41"}
    refused = (await client.post(f"{API}/terms/{term_id}/calendar-groups/import", json={
        "items": [{**item, "plan_version_id": plans[siscom]}]})).json()
    assert refused["created"] == [] and "INUE Online" in refused["skipped"][0]["reason"]
    done = (await client.post(f"{API}/terms/{term_id}/calendar-groups/import", json={
        "items": [{**item, "plan_version_id": plans[online]}]})).json()
    assert done["created"] == ["B41"]
    b41 = next(g for g in (await client.get(f"{API}/groups?term_id={term_id}")).json() if g["code"] == "B41")
    assert b41["campus_id"] == online


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


async def test_each_campus_has_its_own_kardex_logo(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    url = f"{API}/campuses/{campus_id}/logo"
    assert (await client.get(url)).status_code == 404

    up = await client.post(url, files={"file": ("logo.png", PNG, "image/png")})
    assert up.status_code == 200, up.text
    assert up.json()["logo_updated_at"]
    got = await client.get(url)
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-type"] == "image/png"
    listed = {c["id"]: c for c in (await client.get(f"{API}/campuses")).json()}
    assert listed[campus_id]["logo_updated_at"]

    # only PNG/JPG: the PDF can't embed other formats
    bad = await client.post(url, files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")})
    assert bad.status_code == 415

    removed = await client.delete(url)
    assert removed.status_code == 200 and removed.json()["logo_updated_at"] is None
    assert (await client.get(url)).status_code == 404
