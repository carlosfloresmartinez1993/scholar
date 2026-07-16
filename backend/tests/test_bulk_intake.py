"""Bulk cohort intake: create + enroll + auto-bill a roster of NEW students into
one group in a single request, with per-row error reporting (RT-09, RF-T02)."""
from tests.conftest import login
from tests.test_academic_flow import CURP_A, build_catalog
from tests.test_treasury_documents import make_student

# Valid CURPs per CURP_RE: [A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[0-9A-Z]\d
VALID = ["MARA010101HBCXNS01", "LOPE020202MDFXYZ02", "GARC030303HABCDE03"]


async def test_bulk_intake_creates_enrolls_and_bills(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]
    await client.post("/api/v1/treasury/concepts", json={
        "name": "Colegiatura", "kind": "colegiatura", "amount": 2500})

    rows = [{"curp": c, "full_name": f"Alumno {i}", "email": ""} for i, c in enumerate(VALID)]
    res = (await client.post("/api/v1/students/bulk-intake", json={
        "group_id": group_id, "rows": rows})).json()
    assert res["enrolled"] == 3
    assert res["errors"] == []

    students = (await client.get("/api/v1/students?limit=200")).json()
    by_curp = {s["curp"]: s for s in students}
    assert set(VALID) <= set(by_curp)
    # spot-check one student got the 4 colegiaturas
    sid = by_curp[VALID[0]]["id"]
    statement = (await client.get(f"/api/v1/treasury/students/{sid}/statement")).json()
    cole = [c for c in statement["charges"] if c["description"].startswith("Colegiatura")]
    assert len(cole) == 4


async def test_bulk_intake_reports_bad_rows(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]
    await make_student(client, campus_id, curp=CURP_A)  # pre-existing

    rows = [
        {"curp": VALID[0], "full_name": "Nuevo Uno", "email": ""},   # ok
        {"curp": CURP_A, "full_name": "Existente", "email": ""},      # already registered
        {"curp": "BADCURP", "full_name": "Malo", "email": ""},        # invalid CURP
        {"curp": VALID[0], "full_name": "Repetido", "email": ""},     # duplicate in file
    ]
    res = (await client.post("/api/v1/students/bulk-intake", json={
        "group_id": group_id, "rows": rows})).json()

    assert res["enrolled"] == 1
    by_row = {e["row"]: e["detail"] for e in res["errors"]}
    assert set(by_row) == {2, 3, 4}
    assert "CURP" in by_row[2]              # already exists
    assert by_row[3]                        # invalid CURP (validation message)
    assert "duplicada" in by_row[4]         # repeated within the roster
