"""Sincronización con el sistema de calendario: scholar keeps its own copy of the
calendar's campuses and programs, linked by the calendar id.

The calendar is read-only for scholar, and each side may be edited on its own: a
sync creates what is missing and links what matches, but never overwrites a row
already linked — a difference is only reported. What only scholar has (address,
plan de estudios, RVOE dates) is never touched. Neither function commits."""
import re
import unicodedata
import uuid

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Campus, EducationLevel, Institution, Program, Rvoe
from app.services import audit, calendar


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", plain.upper()).strip()


# --- Planteles ------------------------------------------------------------------

async def sync_campuses(session: AsyncSession, user, institution: Institution) -> dict:
    """Every campus of the calendar exists in scholar: linked ones are left as they
    are, one with the same name is linked, the rest are created."""
    existing = (
        await session.exec(select(Campus).where(Campus.institution_id == institution.id))
    ).all()
    by_calendar = {str(c.calendar_campus_id): c for c in existing if c.calendar_campus_id}
    by_name = {_norm(c.name): c for c in existing if not c.calendar_campus_id}
    result: dict[str, list] = {"created": [], "linked": [], "different": [], "unchanged": []}
    for cal in await calendar.get_campuses():
        campus = by_calendar.get(str(cal["id"]))
        if campus is not None:
            if campus.name != cal["name"]:
                result["different"].append({"scholar": campus.name, "calendar": cal["name"]})
            else:
                result["unchanged"].append(campus.name)
            continue
        campus = by_name.get(_norm(cal["name"]))
        if campus is not None:
            campus.calendar_campus_id = uuid.UUID(cal["id"])
            result["linked"].append(campus.name)
        else:
            campus = Campus(
                institution_id=institution.id, name=cal["name"],
                is_active=cal.get("is_active", True), calendar_campus_id=uuid.UUID(cal["id"]),
            )
            result["created"].append(campus.name)
        session.add(campus)
    if result["created"] or result["linked"]:
        audit.record(
            session, actor=user.email, action="campus.synced_from_calendar", entity="institution",
            entity_id=str(institution.id),
            detail=f"creados: {', '.join(result['created']) or '—'}; vinculados: {', '.join(result['linked']) or '—'}",
        )
    await session.flush()
    return result


# --- Carreras -------------------------------------------------------------------

def _code_for(name: str, taken: set[str]) -> str:
    """A program code from its name (the calendar has none): unique, 32 chars."""
    base = _norm(name).replace(" ", "-")[:28] or "CARRERA"
    code, n = base, 2
    while code in taken:
        code, n = f"{base}-{n}", n + 1
    taken.add(code)
    return code


async def programs_preview(session: AsyncSession, institution: Institution) -> list[dict]:
    """Each program of the calendar with what an import would do with it."""
    programs = (
        await session.exec(select(Program).where(Program.institution_id == institution.id))
    ).all()
    by_calendar = {str(p.calendar_program_id): p for p in programs if p.calendar_program_id}
    by_name = {_norm(p.name): p for p in programs if not p.calendar_program_id}
    rvoes = {r.agreement_number: r for r in (await session.exec(select(Rvoe))).all()}
    campuses = {
        str(c.calendar_campus_id): c
        for c in (await session.exec(select(Campus).where(Campus.institution_id == institution.id))).all()
        if c.calendar_campus_id
    }
    levels = {level.value for level in EducationLevel}
    rows = []
    for cal in sorted(await calendar.get_programs(), key=lambda p: p["name"]):
        number = (cal.get("rvoe") or "").strip()
        campus = campuses.get(str(cal.get("campus_id")))
        program = by_calendar.get(str(cal["id"]))
        rvoe = rvoes.get(number) if number else None
        problems = []
        if cal.get("level") not in levels:
            problems.append(f"Nivel «{cal.get('level')}» no existe en Scholar")
        if campus is None:
            problems.append("Su plantel no está sincronizado")
        if program is not None:
            status = "sincronizada"
            if program.name != cal["name"]:
                status = "diferente"
        elif rvoe is not None or _norm(cal["name"]) in by_name:
            status = "vincular"  # it exists here: only the link is missing
            program = (await session.get(Program, rvoe.program_id)) if rvoe else by_name[_norm(cal["name"])]
        else:
            status = "nueva"
        rows.append({
            "calendar_program_id": cal["id"], "name": cal["name"], "level": cal.get("level"),
            "rvoe": number or None, "campus": campus.name if campus else None,
            "status": "no_importable" if problems and status == "nueva" else status,
            "problems": problems,
            "program_id": str(program.id) if program else None,
            "scholar_name": program.name if program else None,
            "has_rvoe": rvoe is not None,
        })
    return rows


async def import_programs(
    session: AsyncSession, user, institution: Institution, calendar_program_ids: list
) -> dict:
    """Create (or link) the chosen programs. The RVOE itself is not created: the
    calendar only knows its number — its date and authority are captured in scholar."""
    wanted = {str(i) for i in calendar_program_ids}
    if not wanted:
        raise HTTPException(status_code=400, detail="Seleccione al menos una carrera")
    preview = {row["calendar_program_id"]: row for row in await programs_preview(session, institution)}
    taken = {
        p.code for p in (
            await session.exec(select(Program).where(Program.institution_id == institution.id))
        ).all()
    }
    result: dict[str, list] = {"created": [], "linked": [], "skipped": []}
    for cal_id in wanted:
        row = preview.get(cal_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Carrera del calendario no encontrada")
        if row["status"] == "nueva":
            program = Program(
                institution_id=institution.id, code=_code_for(row["name"], taken), name=row["name"],
                level=EducationLevel(row["level"]), calendar_program_id=uuid.UUID(cal_id),
            )
            session.add(program)
            result["created"].append(row["name"])
        elif row["status"] == "vincular":
            program = await session.get(Program, uuid.UUID(row["program_id"]))
            program.calendar_program_id = uuid.UUID(cal_id)
            session.add(program)
            result["linked"].append(row["name"])
        else:
            result["skipped"].append({"name": row["name"], "reason": "; ".join(row["problems"]) or "ya sincronizada"})
    if result["created"] or result["linked"]:
        audit.record(
            session, actor=user.email, action="program.imported_from_calendar", entity="institution",
            entity_id=str(institution.id),
            detail=f"creadas: {', '.join(result['created']) or '—'}; vinculadas: {', '.join(result['linked']) or '—'}",
        )
    await session.flush()
    return result
