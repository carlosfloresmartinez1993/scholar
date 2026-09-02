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
import zipfile
from collections.abc import Iterable
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
MAX_COLS = 200  # a roster is dozens of columns wide; a sheet declares up to 16384
# one row past what a header block + a full batch can need, so parse_roster can
# still tell that the file had more
READ_MAX_ROWS = HEADER_SCAN_ROWS + MAX_ROWS


def normalize_header(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


# the CURP's 11th character is the official sex: H = hombre, M = mujer
_SEX_BY_CURP = {"H": "M", "M": "F"}


def normalize_sex(value: str | None, curp: str | None = None) -> str | None:
    """'Femenino'/'Mujer'/'F' -> 'F', 'Masculino'/'Hombre'/'H' -> 'M'. Empty ->
    None. Anything else raises so the row is reported instead of mis-recorded.

    A bare 'M' is ambiguous — Mexican records write both F/M (M = Masculino) and
    H/M (M = Mujer) — so it is resolved against the CURP's sex character, which
    every intake row carries. A column that contradicts the CURP raises too,
    instead of storing an inverted sex nobody can spot afterwards."""
    if value is None or not value.strip():
        return None
    key = normalize_header(value)
    text = (curp or "").strip().upper()
    curp_sex = _SEX_BY_CURP.get(text[10]) if len(text) > 10 else None
    if key in {"f", "femenino", "mujer", "female"}:
        sex = "F"
    elif key in {"h", "hombre", "masculino", "male"}:
        sex = "M"
    elif key == "m":
        sex = curp_sex or "M"  # no CURP to decide: assume the F/M convention
    else:
        raise ValueError(f"Sexo inválido: {value!r}")
    if curp_sex is not None and sex != curp_sex:
        raise ValueError(f"Sexo {value!r} no coincide con la CURP")
    return sex


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


def _cell_text(value: Any, number_format: str = "General") -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    numeric = isinstance(value, int | float) and not isinstance(value, bool)
    if numeric and float(value).is_integer():
        # Excel stores phones/matrículas as numbers; when the cell is displayed
        # zero-padded ("00000000") the padding is part of the matrícula
        text = str(int(value))
        if number_format and set(number_format) == {"0"}:
            text = text.zfill(len(number_format))
        return text
    return str(value).strip()


def _take_rows(rows: Iterable[list[str]]) -> list[list[str]]:
    """Collect at most one row more than bulk intake can ever use, dropping the
    blank ones. Reading is bounded here (not after building the whole grid): an
    .xlsx is zip-compressed and openpyxl pads every row out to the sheet's
    declared width, so a small upload can otherwise expand to gigabytes."""
    out: list[list[str]] = []
    for row in rows:
        if not any(cell for cell in row):
            continue
        out.append(row)
        if len(out) > READ_MAX_ROWS:
            break
    return out


def _read_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    # read_only parsing is lazy, so a corrupt workbook can raise while iterating
    unreadable = (InvalidFileException, KeyError, OSError, ValueError, zipfile.BadZipFile)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except unreadable as e:
        raise HTTPException(status_code=400, detail="El archivo .xlsx no se pudo leer") from e
    try:
        # the first sheet with any content — Servo exports are single-sheet, but
        # a hand-made workbook may carry an empty "Hoja1" first
        for sheet in workbook.worksheets:
            rows = _take_rows(
                [_cell_text(c.value, getattr(c, "number_format", "General"))
                 for c in row[:MAX_COLS]]
                for row in sheet.iter_rows()
            )
            if rows:
                return rows
        return []
    except unreadable as e:
        raise HTTPException(status_code=400, detail="El archivo .xlsx no se pudo leer") from e
    finally:
        workbook.close()


def _sniff_delimiter(sample: str) -> str:
    """Pick the delimiter whose field count most lines agree on. csv.Sniffer
    chokes on the title block Servo puts above the grid (a ragged line with no
    delimiter) and its fallback only knew tab vs comma, which silently read a
    ';' export — Excel's default in es-MX — as a single column."""
    lines = [line for line in sample.splitlines() if line.strip()][:30]
    best_score, best = 0, ""
    for delimiter in (",", ";", "\t", "|"):
        try:
            counts = [len(row) for row in csv.reader(lines, delimiter=delimiter) if len(row) > 1]
        except csv.Error:
            continue
        if not counts:
            continue
        common = max(set(counts), key=counts.count)
        score = counts.count(common) * common  # agreement, favouring more columns
        if score > best_score:
            best_score, best = score, delimiter
    return best or ("\t" if "\t" in sample else ",")


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
    delimiter = _sniff_delimiter(text[:4096])
    # newline="" is the mode csv documents: without it a CR-only file (Excel's
    # "CSV Macintosh") reaches the reader as one line and blows up
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        return _take_rows([cell.strip() for cell in row[:MAX_COLS]] for row in reader)
    except csv.Error as e:
        raise HTTPException(status_code=400, detail="El archivo .csv no se pudo leer") from e


def read_grid(data: bytes, filename: str | None, content_type: str | None = None) -> list[list[str]]:
    """Raw cell grid from an .xlsx or delimited-text upload."""
    name = (filename or "").lower()
    # sniff the OLE container before the name: a password-protected workbook is
    # an OLE file that keeps its .xlsx extension, and openpyxl only says "not a
    # zip file" about it
    if data[:4] == b"\xd0\xcf\x11\xe0" or name.endswith(".xls"):
        raise HTTPException(
            status_code=400,
            detail="Archivo .xls (Excel 97-2003) o protegido con contraseña: "
                   "guárdelo como .xlsx sin contraseña, o como .csv",
        )
    if name.endswith(".xlsx") or name.endswith(".xlsm") or data[:2] == b"PK":
        return _read_xlsx(data)
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
    # a lone "Nombre" column with no apellidos is the whole name, not the given
    # names — but never over a column that already names the whole student
    if (
        "first_names" in mapping
        and "full_name" not in mapping
        and not ({"last_name_p", "last_name_m"} & mapping.keys())
    ):
        mapping["full_name"] = mapping.pop("first_names")
    return index, mapping


def parse_roster(data: bytes, filename: str | None, content_type: str | None = None) -> dict:
    """Parse an uploaded roster into {columns, mapping, rows, header_row,
    truncated, skipped}. Without a recognizable header the file is taken as the
    legacy positional layout (CURP, Nombre, Email) with every row as data."""
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
        # reported, not hidden: with a partly detected header these may be real
        # students whose only recognized identity column happens to be blank
        "skipped": len(padded) - len(rows),
    }
