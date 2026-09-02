"""Roster file parsing for bulk intake: turn a servoescolar.mx export (or any
.xlsx / .csv roster) into a column grid plus a best-effort mapping from our
intake fields to its columns.

Servo has no published export layout and its grids are exported straight from
whatever the operator had on screen, so nothing here assumes a column order:
the header row is located by scanning the top of the sheet for recognizable
Spanish headers (CURP, Matrícula, Apellido paterno, …), title/blank rows above
it are ignored, and the caller (the UI) can still remap any field by hand."""
import csv
import io
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException

# Intake fields a roster column can feed, in the order the UI presents them.
ROSTER_FIELDS: tuple[str, ...] = (
    "curp",
    "enrollment_number",
    "full_name",
    "first_names",
    "last_name_p",
    "last_name_m",
    "email",
    "phone",
    "sex",
    "birth_date",
)

# normalized header text -> field. Normalization drops accents, case and every
# non-alphanumeric char, so "Apellido Paterno", "APELLIDO_PATERNO" and
# "apellido-paterno" all land on the same key.
_ALIASES: dict[str, str] = {
    "curp": "curp",
    "clavecurp": "curp",
    "matricula": "enrollment_number",
    "nomatricula": "enrollment_number",
    "nummatricula": "enrollment_number",
    "numerodematricula": "enrollment_number",
    "matriculaalumno": "enrollment_number",
    "nombrecompleto": "full_name",
    "nombredelalumno": "full_name",
    "nombrealumno": "full_name",
    "alumno": "full_name",
    "alumnoa": "full_name",
    "estudiante": "full_name",
    "nombres": "first_names",
    "nombre": "first_names",  # demoted to full_name when no apellido column exists
    "nombresdelalumno": "first_names",
    "apellidopaterno": "last_name_p",
    "apaterno": "last_name_p",
    "apellidop": "last_name_p",
    "paterno": "last_name_p",
    "primerapellido": "last_name_p",
    "apellido1": "last_name_p",
    "apellidos": "last_name_p",
    "apellidomaterno": "last_name_m",
    "amaterno": "last_name_m",
    "apellidom": "last_name_m",
    "materno": "last_name_m",
    "segundoapellido": "last_name_m",
    "apellido2": "last_name_m",
    "email": "email",
    "emails": "email",
    "correo": "email",
    "correoelectronico": "email",
    "correoalumno": "email",
    "mail": "email",
    "telefono": "phone",
    "telefonocelular": "phone",
    "telefonomovil": "phone",
    "celular": "phone",
    "movil": "phone",
    "tel": "phone",
    "sexo": "sex",
    "genero": "sex",
    "fechadenacimiento": "birth_date",
    "fechanacimiento": "birth_date",
    "fechanac": "birth_date",
    "fecnac": "birth_date",
    "nacimiento": "birth_date",
}

_NAME_PART_FIELDS = {"first_names", "last_name_p", "last_name_m"}
_IDENTITY_FIELDS = _NAME_PART_FIELDS | {"curp", "full_name"}
HEADER_SCAN_ROWS = 30  # Servo reports put a title block above the grid
MAX_ROWS = 1000  # mirrors BulkIntakeIn.rows


def normalize_header(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_sex(value: str | None) -> str | None:
    """'Femenino'/'Mujer'/'F' -> 'F', 'Masculino'/'Hombre'/'M' -> 'M'. Empty ->
    None. Anything else raises so the row is reported instead of mis-recorded."""
    if value is None or not value.strip():
        return None
    key = normalize_header(value)
    if key in {"f", "femenino", "mujer", "female"}:
        return "F"
    if key in {"m", "masculino", "hombre", "male"}:
        return "M"
    raise ValueError(f"Sexo inválido: {value!r}")


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d")


def normalize_date(value: str | None) -> date | None:
    """Accept ISO and the day-first forms Mexican exports use. Empty -> None."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    text = text.split(" ")[0].split("T")[0]  # drop a time part ("01/02/2003 00:00:00")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha de nacimiento inválida: {value!r}")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # Excel stores phones/matrículas as numbers
    return str(value).strip()


def _read_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, KeyError, OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail="El archivo .xlsx no se pudo leer") from e
    try:
        # the first sheet with any content — Servo exports are single-sheet, but
        # a hand-made workbook may carry an empty "Hoja1" first
        for sheet in workbook.worksheets:
            rows = [[_cell_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
            if any(any(cell for cell in row) for row in rows):
                return rows
        return []
    finally:
        workbook.close()


def _read_csv(data: bytes) -> list[list[str]]:
    text: str
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader]


def read_grid(data: bytes, filename: str | None, content_type: str | None = None) -> list[list[str]]:
    """Raw cell grid from an .xlsx or delimited-text upload."""
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm") or data[:2] == b"PK":
        return _read_xlsx(data)
    if name.endswith(".xls") or data[:4] == b"\xd0\xcf\x11\xe0":
        raise HTTPException(
            status_code=400,
            detail="Formato .xls (Excel 97-2003) no soportado: guárdelo como .xlsx o .csv",
        )
    return _read_csv(data)


def _detect_header(grid: list[list[str]]) -> tuple[int | None, dict[str, int]]:
    """Find the header row: the best-scoring row (most alias hits) among the
    first HEADER_SCAN_ROWS that names at least a CURP or a name column."""
    best: tuple[int, int, dict[str, int]] | None = None  # (score, row index, mapping)
    for i, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        mapping: dict[str, int] = {}
        for j, cell in enumerate(row):
            field = _ALIASES.get(normalize_header(cell))
            if field and field not in mapping:  # first occurrence wins
                mapping[field] = j
        if not mapping:
            continue
        if "curp" not in mapping and not (mapping.keys() & (_NAME_PART_FIELDS | {"full_name"})):
            continue
        score = len(mapping)
        if best is None or score > best[0]:
            best = (score, i, mapping)
    if best is None:
        return None, {}
    _, index, mapping = best
    # a lone "Nombre" column with no apellidos is the whole name, not the given names
    if "first_names" in mapping and not ({"last_name_p", "last_name_m"} & mapping.keys()):
        mapping["full_name"] = mapping.pop("first_names")
    return index, mapping


def parse_roster(data: bytes, filename: str | None, content_type: str | None = None) -> dict:
    """Parse an uploaded roster into {columns, mapping, rows, header_row, truncated}.
    Without a recognizable header the file is taken as the legacy positional
    layout (CURP, Nombre, Email) with every row as data."""
    grid = read_grid(data, filename, content_type)
    grid = [row for row in grid if any(cell for cell in row)]  # drop blank lines
    if not grid:
        raise HTTPException(status_code=400, detail="El archivo no contiene filas")
    header_row, mapping = _detect_header(grid)
    width = max(len(row) for row in grid)
    if header_row is None:
        # legacy paste/CSV: curp, nombre, email — never silently drop the first row
        mapping = {f: i for i, f in enumerate(("curp", "full_name", "email")) if i < width}
        columns = [f"Columna {i + 1}" for i in range(width)]
        data_rows = grid
    else:
        header = grid[header_row]
        columns = [
            (header[i] if i < len(header) and header[i] else f"Columna {i + 1}")
            for i in range(width)
        ]
        data_rows = grid[header_row + 1:]
    padded = [row + [""] * (width - len(row)) for row in data_rows]
    identity_cols = {c for f, c in mapping.items() if f in _IDENTITY_FIELDS}
    # keep a row only if it names someone: a "Total: 25" footer under Matrícula is
    # noise, but a row with a name and a bad CURP is data to report, not to drop
    rows = [row for row in padded if any(row[c] for c in identity_cols)]
    truncated = len(rows) > MAX_ROWS
    return {
        "columns": columns,
        "mapping": {f: mapping.get(f) for f in ROSTER_FIELDS},
        "rows": rows[:MAX_ROWS],
        "header_row": header_row,
        "truncated": truncated,
    }
