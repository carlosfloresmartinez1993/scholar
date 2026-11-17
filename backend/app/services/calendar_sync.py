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

from app.api.deps import ensure_in_scope
from app.models import (
    Campus,
    Group,
    GroupSubject,
    Institution,
    PlanSubject,
    PlanVersion,
    Program,
    Rvoe,
    Term,
)
from app.services.academics import require_operable_rvoe
from app.services.levels import levels_of
from app.services.rvoe_campuses import campus_ids_of, campus_map
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
    levels = {level.code for level in await levels_of(session, institution.id, active_only=True)}
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
                level=row["level"], calendar_program_id=uuid.UUID(cal_id),
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


# --- Grupos ----------------------------------------------------------------------

async def seed_group_subjects(session: AsyncSession, group: Group) -> int:
    """A group starts with the plan subjects of its cuatrimestre (teacher unassigned)."""
    subjects = (
        await session.exec(
            select(PlanSubject).where(
                PlanSubject.plan_version_id == group.plan_version_id,
                PlanSubject.period_number == group.period_number,
            )
        )
    ).all()
    for subject in subjects:
        session.add(GroupSubject(group_id=group.id, plan_subject_id=subject.id))
    await session.flush()
    return len(subjects)


def period_from_code(code: str) -> int | None:
    """The cuatrimestre a calendar group code suggests: the first digit after its
    letters (PSI31 -> 3, AD91S -> 9, TCM1 -> 1). The user confirms it."""
    match = re.match(r"^[A-Za-z]*-?(\d)", code or "")
    return int(match.group(1)) if match and match.group(1) != "0" else None


async def groups_preview(session: AsyncSession, term: Term) -> dict:
    """Each group the calendar has for this term with the plan and cuatrimestre it
    would get here, or why it can't come yet."""
    if term.calendar_term_id is None:
        raise HTTPException(
            status_code=409,
            detail="Este ciclo no viene del calendario: impórtalo desde Periodos para traer sus grupos",
        )
    programs = {
        str(p.calendar_program_id): p
        for p in (await session.exec(select(Program).where(Program.calendar_program_id.is_not(None)))).all()  # type: ignore[union-attr]
    }
    campuses = {
        str(c.calendar_campus_id): c
        for c in (await session.exec(select(Campus).where(Campus.calendar_campus_id.is_not(None)))).all()  # type: ignore[union-attr]
    }
    imported = {
        str(g.calendar_group_id): g
        for g in (await session.exec(select(Group).where(Group.term_id == term.id))).all()
        if g.calendar_group_id
    }
    plan_rows = (
        await session.exec(
            select(PlanVersion, Rvoe, Campus)
            .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
            .join(Campus, Campus.id == Rvoe.campus_id)
            .where(PlanVersion.is_active == True)  # noqa: E712
            .order_by(PlanVersion.created_at.desc())  # type: ignore[attr-defined]
        )
    ).all()
    offered = await campus_map(session, [rvoe for _, rvoe, _ in plan_rows])
    rows = []
    for cal in sorted(await calendar.get_groups(term_id=term.calendar_term_id), key=lambda g: g["code"]):
        program = programs.get(str(cal.get("program_id")))
        campus = campuses.get(str(cal.get("campus_id")))
        plans = []
        if program is not None:
            plans = [
                {"plan_version_id": str(plan.id),
                 "label": f"{rvoe.agreement_number} · Plan {plan.version_label} · {cam.name}",
                 "periods_count": plan.periods_count,
                 "same_campus": campus is not None and campus.id in offered[rvoe.id],
                 "operable": rvoe.is_operable()}
                for plan, rvoe, cam in plan_rows if rvoe.program_id == program.id
            ]
            plans.sort(key=lambda p: (not p["same_campus"], not p["operable"]))
        existing = imported.get(str(cal["id"]))
        if existing is not None:
            status, reason = "importado", f"Ya está en Scholar como {existing.code}"
        elif program is None:
            status, reason = "sin_carrera", "Su carrera no se ha importado del calendario"
        elif not plans:
            status, reason = "sin_plan", "Su carrera no tiene RVOE con plan de estudios en Scholar"
        else:
            status, reason = "nuevo", None
        rows.append({
            "calendar_group_id": cal["id"], "code": cal["code"],
            "program": program.name if program else None,
            "campus": campus.name if campus else None,
            "suggested_period": period_from_code(cal["code"]),
            "plans": plans, "status": status, "reason": reason,
        })
    return {"term_id": str(term.id), "term_name": term.name, "groups": rows}


async def import_groups(session: AsyncSession, user, term: Term, items: list[dict], scope) -> dict:
    """Create each chosen group with the plan and cuatrimestre confirmed by the user;
    a group already imported or whose code is taken is skipped. Caller commits."""
    if not items:
        raise HTTPException(status_code=400, detail="Seleccione al menos un grupo")
    if term.calendar_term_id is None:
        raise HTTPException(status_code=409, detail="Este ciclo no viene del calendario")
    calendar_groups = {str(g["id"]): g for g in await calendar.get_groups(term_id=term.calendar_term_id)}
    calendar_ids = set(calendar_groups)
    result: dict[str, list] = {"created": [], "skipped": []}
    for item in items:
        code = item["code"].strip()
        cal_id = item["calendar_group_id"]
        item["calendar_campus_id"] = (calendar_groups.get(str(cal_id)) or {}).get("campus_id")
        if str(cal_id) not in calendar_ids:
            result["skipped"].append({"code": code, "reason": "No es un grupo de este ciclo en el calendario"})
            continue
        if (await session.exec(select(Group.id).where(Group.calendar_group_id == cal_id))).first():
            result["skipped"].append({"code": code, "reason": "Ya se importó"})
            continue
        plan = await session.get(PlanVersion, item["plan_version_id"])
        if plan is None:
            result["skipped"].append({"code": code, "reason": "Plan de estudios no encontrado"})
            continue
        if item["period_number"] > plan.periods_count:
            result["skipped"].append({"code": code, "reason": f"El plan tiene {plan.periods_count} periodos"})
            continue
        try:
            rvoe = await require_operable_rvoe(session, plan.id)
        except HTTPException as error:
            result["skipped"].append({"code": code, "reason": error.detail})
            continue
        # the calendar's plantel when the RVOE is offered there; else the RVOE's main one
        cal_campus = (
            await session.exec(select(Campus).where(Campus.calendar_campus_id == uuid.UUID(str(item["calendar_campus_id"]))))
        ).first() if item.get("calendar_campus_id") else None
        campus_id = (
            cal_campus.id if cal_campus and cal_campus.id in await campus_ids_of(session, rvoe) else rvoe.campus_id
        )
        ensure_in_scope(scope, campus_id)
        clash = (
            await session.exec(
                select(Group.id).where(
                    Group.term_id == term.id, Group.campus_id == campus_id, Group.code == code
                )
            )
        ).first()
        if clash:
            result["skipped"].append({"code": code, "reason": "Ya hay un grupo con esa clave en el ciclo y plantel"})
            continue
        group = Group(
            code=code, period_number=item["period_number"], plan_version_id=plan.id, term_id=term.id,
            campus_id=campus_id, calendar_group_id=cal_id,
        )
        session.add(group)
        await session.flush()
        seeded = await seed_group_subjects(session, group)
        audit.record(session, actor=user.email, action="group.imported_from_calendar",
                     entity="group", entity_id=str(group.id), detail=f"{group.code} · {seeded} materias")
        result["created"].append(code)
    await session.flush()
    return result
