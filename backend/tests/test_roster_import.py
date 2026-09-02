"""Bulk intake from a servoescolar.mx export: header-driven roster parsing
(.xlsx/.csv with a title block, Spanish headers in any order) and intake rows
carrying the split name, sexo, fecha de nacimiento and a preserved matrícula."""
import io
from datetime import datetime

from openpyxl import Workbook

from app.services.roster_import import normalize_date, normalize_sex, parse_roster
from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_bulk_intake import VALID


def servo_xlsx() -> bytes:
    """A Servo-style export: report title block, then a grid whose columns are
    in Servo's order (not ours), dates as real Excel dates, phone as a number,
    and a footer row."""
    wb = Workbook()
    ws = wb.active
    ws.append(["Instituto Universitario Ensenada"])
    ws.append([])
    ws.append(["Alumnos inscritos", "Ciclo: 2026-3", "Plantel: Ensenada"])
    ws.append([
        "Matrícula", "Apellido Paterno", "Apellido Materno", "Nombre(s)", "CURP",
        "Sexo", "Fecha de Nacimiento", "Correo Electrónico", "Teléfono",
    ])
    ws.append([
        "20210123", "MARTÍNEZ", "RAMÍREZ", "ANA SOFÍA", VALID[0],
        "Femenino", datetime(2001, 3, 5), "ana@correo.mx", 6461234567.0,
    ])
    ws.append([
        "20210124", "LÓPEZ", "", "JUAN", VALID[1],
        "Masculino", datetime(2002, 11, 20), "", None,
    ])
    ws.append(["Total de alumnos: 2"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_servo_xlsx_detects_headers_in_any_order():
    parsed = parse_roster(servo_xlsx(), "inscritos.xlsx")
    assert parsed["header_row"] == 2  # blank line dropped, two title rows above
    assert parsed["columns"][0] == "Matrícula"
    assert parsed["mapping"] == {
        "curp": 4, "enrollment_number": 0, "full_name": None, "first_names": 3,
        "last_name_p": 1, "last_name_m": 2, "email": 7, "phone": 8, "sex": 5,
        "birth_date": 6,
    }
    # footer dropped (no name/CURP), data rows kept with normalized cells
    assert len(parsed["rows"]) == 2
    ana = parsed["rows"][0]
    assert ana[6] == "2001-03-05"  # Excel date -> ISO
    assert ana[8] == "6461234567"  # numeric phone -> digits, no ".0"
    assert parsed["truncated"] is False


def test_parse_legacy_csv_with_header_maps_nombre_to_full_name():
    data = "CURP,Nombre,Email\r\n" f"{VALID[0]},Juan Pérez,j@x.mx\r\n".encode("utf-8-sig")
    parsed = parse_roster(data, "alumnos.csv")
    assert parsed["header_row"] == 0
    assert parsed["mapping"]["full_name"] == 1
    assert parsed["mapping"]["first_names"] is None
    assert parsed["rows"] == [[VALID[0], "Juan Pérez", "j@x.mx"]]


def test_parse_headerless_csv_is_positional_and_keeps_first_row():
    data = f"{VALID[0]}\tAlumno Uno\t\n{VALID[1]}\tAlumno Dos\tdos@x.mx\n".encode()
    parsed = parse_roster(data, "pegado.csv")
    assert parsed["header_row"] is None
    assert parsed["mapping"]["curp"] == 0
    assert parsed["mapping"]["full_name"] == 1
    assert parsed["mapping"]["email"] == 2
    assert len(parsed["rows"]) == 2


def test_parse_csv_semicolon_cp1252():
    text = f"CURP;Apellido Paterno;Apellido Materno;Nombres\n{VALID[0]};NÚÑEZ;PEÑA;JOSÉ\n"
    parsed = parse_roster(text.encode("cp1252"), "export.csv")
    assert parsed["mapping"]["last_name_p"] == 1
    assert parsed["rows"][0][1] == "NÚÑEZ"


def test_normalizers():
    assert normalize_sex("Femenino") == "F"
    assert normalize_sex("hombre") == "M"
    assert normalize_sex("") is None
    assert normalize_date("05/03/2001").isoformat() == "2001-03-05"
    assert normalize_date("2001-03-05 00:00:00").isoformat() == "2001-03-05"
    assert normalize_date(" ") is None
    for bad in (normalize_sex, normalize_date):
        try:
            bad("???")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


async def test_parse_endpoint_and_xls_rejection(client, seed):
    await login(client)
    res = await client.post(
        "/api/v1/students/bulk-intake/parse",
        files={"file": ("inscritos.xlsx", servo_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["mapping"]["curp"] == 4
    assert len(res.json()["rows"]) == 2

    res = await client.post(
        "/api/v1/students/bulk-intake/parse",
        files={"file": ("viejo.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64,
                        "application/vnd.ms-excel")},
    )
    assert res.status_code == 400
    assert ".xlsx" in res.json()["detail"]


async def test_bulk_intake_servo_rows_keep_matricula_and_split_name(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]

    rows = [
        {  # full Servo row
            "curp": VALID[0], "enrollment_number": "20210123",
            "first_names": "Ana Sofía", "last_name_p": "Martínez", "last_name_m": "Ramírez",
            "email": "ana@correo.mx", "phone": "6461234567",
            "sex": "Femenino", "birth_date": "05/03/2001",
        },
        {  # same matrícula again -> rejected, the row before is untouched
            "curp": VALID[1], "enrollment_number": "20210123", "full_name": "Juan López",
        },
        {  # bad sexo -> reported, not silently stored
            "curp": VALID[2], "full_name": "Pedro Ruiz", "sex": "X",
        },
    ]
    res = (await client.post("/api/v1/students/bulk-intake", json={
        "group_id": group_id, "rows": rows})).json()
    assert res["enrolled"] == 1, res
    by_row = {e["row"]: e["detail"] for e in res["errors"]}
    assert "matrícula 20210123" in by_row[2]
    assert "Sexo" in by_row[3]

    students = (await client.get("/api/v1/students?limit=200")).json()
    ana = next(s for s in students if s["curp"] == VALID[0])
    assert ana["enrollment_number"] == "20210123"
    assert ana["full_name"] == "Ana Sofía Martínez Ramírez"
    assert ana["last_name_p"] == "Martínez"
    assert ana["sex"] == "F"
    assert ana["birth_date"] == "2001-03-05"
    assert ana["phone"] == "6461234567"


async def test_preserved_our_style_matricula_bumps_counter(client, seed):
    """Importing INUE000050 must push the MAT counter past 50 so the next
    allocation can't collide with it."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    group_id = catalog["group"]["id"]
    # a first regular create seeds the counter (INUE000001)
    first = (await client.post("/api/v1/students", json={
        "curp": VALID[0], "full_name": "Primero", "campus_id": campus_id})).json()
    assert first["enrollment_number"] == "INUE000001"

    res = (await client.post("/api/v1/students/bulk-intake", json={
        "group_id": group_id,
        "rows": [{"curp": VALID[1], "full_name": "Migrado", "enrollment_number": "inue000050"}],
    })).json()
    assert res["errors"] == []

    nxt = (await client.post("/api/v1/students", json={
        "curp": VALID[2], "full_name": "Siguiente", "campus_id": campus_id})).json()
    assert nxt["enrollment_number"] == "INUE000051"
