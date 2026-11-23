"""Historia del alumno: what happened with them, in order — ingreso, each cuatrimestre
(group and how the subjects went), bajas and reingresos, cambios de RVOE,
reconocimientos, materias in another group and grade corrections. Read from what
is already recorded (group enrollments, plan changes and the audit log); nothing
here is stored."""
import re
import uuid
from collections import defaultdict
from datetime import datetime, time

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    AuditLog,
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    GroupSubject,
    PlanChange,
    PlanSubject,
    PlanVersion,
    Program,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    Term,
)
from app.services.academics import current_group, recognition_kind

STATUS_LABELS = {
    "activo": "Activo",
    "baja_temporal": "Baja temporal",
    "baja_definitiva": "Baja definitiva",
    "egresado": "Egresado",
}
RECOGNITION_LABELS = {"eq": "equivalencia", "rev": "revalidación", "conv": "convalidación"}
_STATUS_CHANGE = re.compile(r"status: (?:StudentStatus\.)?(\w+) -> (?:StudentStatus\.)?(\w+)")
_CORRECTION = re.compile(r"^(\S+): (\S+) -> (\S+)(?: — (.*))?$")


def _grade(value: str) -> str:
    """«None» → «sin calificación»; 9.0 → 9."""
    if value in ("None", ""):
        return "sin calificación"
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return value


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _subjects_line(counts: dict) -> str:
    parts = []
    if counts.get("aprobada"):
        parts.append(_plural(counts["aprobada"], "aprobada"))
    if counts.get("reprobada"):
        parts.append(_plural(counts["reprobada"], "reprobada"))
    if counts.get("cursando"):
        parts.append(f"{counts['cursando']} en curso")
    if counts.get("baja"):
        parts.append(_plural(counts["baja"], "retirada"))
    return " · ".join(parts) or "sin materias"


async def student_history(session: AsyncSession, student: Student) -> dict:
    sid = student.id
    rows = (
        await session.exec(
            select(GroupEnrollment, Group, Term, Program, Rvoe, PlanVersion)
            .join(Group, Group.id == GroupEnrollment.group_id)
            .join(Term, Term.id == Group.term_id)
            .join(PlanVersion, PlanVersion.id == Group.plan_version_id)
            .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
            .join(Program, Program.id == Rvoe.program_id)
            .where(GroupEnrollment.student_id == sid)
            .order_by(Term.start_date, GroupEnrollment.created_at)  # type: ignore[arg-type]
        )
    ).all()
    # how the subjects went in each group enrollment, and their codes
    counts: dict = defaultdict(lambda: defaultdict(int))
    codes: dict = defaultdict(list)
    for ge_id, status, code in (
        await session.exec(
            select(SubjectEnrollment.group_enrollment_id, SubjectEnrollment.status, PlanSubject.code)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .where(SubjectEnrollment.student_id == sid)
        )
    ).all():
        counts[ge_id][status.value] += 1
        codes[ge_id].append(code)

    audits = (
        await session.exec(
            select(AuditLog).where(AuditLog.entity == "student", AuditLog.entity_id == str(sid))
            .order_by(AuditLog.created_at)  # type: ignore[arg-type]
        )
    ).all()
    status_changes = []
    for a in audits:
        m = _STATUS_CHANGE.search(a.detail or "")
        if a.action == "student.updated" and m and m.group(1) != m.group(2):
            status_changes.append((a.created_at, m.group(1), m.group(2), a.actor))

    events: list[dict] = []

    def add(when: datetime, kind: str, title: str, detail: str = "", term: str | None = None,
            actor: str | None = None):
        events.append({"date": when.isoformat(), "kind": kind, "title": title, "detail": detail,
                       "term": term, "actor": actor})

    # the highest cuatrimestre the student is in, per cycle and plan: a lower group in
    # that same cycle is a recursamiento, not going back
    top: dict = {}
    for ge, group, term, _, _, plan in rows:
        if not ge.subjects_only and not recognition_kind(group.code):
            key = (term.id, plan.id)
            top[key] = max(top.get(key, 0), group.period_number)

    last_regular = None  # (term_id, period, when, plan_version_id)
    for ge, group, term, program, rvoe, plan in rows:
        when = datetime.combine(term.start_date, time.min)
        line = _subjects_line(counts[ge.id])
        kind_code = recognition_kind(group.code)
        if kind_code:
            add(when, "reconocimiento",
                f"Reconocimiento por {RECOGNITION_LABELS.get(kind_code, kind_code)}",
                f"{_plural(len(codes[ge.id]), 'materia')}: {', '.join(sorted(codes[ge.id]))}", term.name)
            continue
        if ge.subjects_only:
            add(when, "otro_grupo", f"Cursa materias con el grupo {group.code}",
                f"{', '.join(sorted(codes[ge.id]))} · {line}", term.name)
            continue
        if group.period_number < top.get((term.id, plan.id), 0):
            add(when, "recursa", f"Recursa materias de {group.period_number}.º con el grupo {group.code}",
                f"{', '.join(sorted(codes[ge.id]))} · {line}", term.name)
            continue
        if last_regular is None:
            title, kind = f"Ingresó a {program.name} — grupo {group.code} ({group.period_number}.º)", "ingreso"
        elif last_regular[0] == term.id and last_regular[1] == group.period_number:
            if last_regular[3] != plan.id:  # cambio de RVOE: same cuatrimestre, new plan
                title, kind = (f"Sigue en {group.period_number}.º con el RVOE {rvoe.agreement_number}"
                               f" — grupo {group.code}"), "rvoe"
            else:
                title, kind = f"Cambió al grupo {group.code}", "cambio_grupo"
        elif any(last_regular[2] < c[0] <= when and c[2].startswith("baja") for c in status_changes):
            title, kind = f"Reingreso en {group.period_number}.º — grupo {group.code}", "reingreso"
        elif group.period_number == last_regular[1]:
            # did not pass the cuatrimestre: takes it again in a later cycle
            title, kind = f"Repite {group.period_number}.º — grupo {group.code}", "repite"
        elif group.period_number < last_regular[1]:
            title, kind = f"Volvió a {group.period_number}.º — grupo {group.code}", "cuatrimestre"
        else:
            title, kind = f"Pasó a {group.period_number}.º — grupo {group.code}", "cuatrimestre"
        if last_regular is not None and last_regular[3] != plan.id and kind not in ("cambio_grupo", "rvoe"):
            title += f" (RVOE {rvoe.agreement_number})"
        moved_out = ge.status == GroupEnrollmentStatus.baja and not counts[ge.id].get("aprobada")
        retakes = " (recursamiento)" if kind == "repite" else ""
        add(when, kind, title, line + retakes + (" · salió del grupo" if moved_out else ""), term.name)
        last_regular = (term.id, group.period_number, when, plan.id)

    for when, before, after, actor in status_changes:
        label = STATUS_LABELS.get(after, after)
        kind = "baja" if after.startswith("baja") else "estatus"
        title = label if after != "activo" else f"Activo de nuevo (antes: {STATUS_LABELS.get(before, before)})"
        add(when, kind, title, "", None, actor)

    # cambios de RVOE (not reverted)
    for change in (
        await session.exec(select(PlanChange).where(PlanChange.student_id == sid, PlanChange.reverted_at.is_(None)))  # type: ignore[union-attr]
    ).all():
        labels = []
        for pe_id in (change.from_plan_enrollment_id, change.to_plan_enrollment_id):
            pe = await session.get(StudentPlanEnrollment, pe_id) if pe_id else None
            pv = await session.get(PlanVersion, pe.plan_version_id) if pe else None
            rv = await session.get(Rvoe, pv.rvoe_id) if pv else None
            labels.append(rv.agreement_number if rv else "?")
        add(change.created_at, "rvoe", f"Cambio de RVOE: {labels[0]} → {labels[1]}", "", None,
            change.changed_by or None)

    # grade corrections, with their motivo
    se_ids = [
        str(i) for i in (await session.exec(select(SubjectEnrollment.id).where(SubjectEnrollment.student_id == sid))).all()
    ]
    if se_ids:
        # corrections made together (same person, same motivo, same minute) are one event
        batches: dict = {}
        for a in (
            await session.exec(
                select(AuditLog).where(
                    AuditLog.action == "subject_enrollment.corrected",
                    AuditLog.entity_id.in_(se_ids),  # type: ignore[union-attr]
                ).order_by(AuditLog.created_at)  # type: ignore[arg-type]
            )
        ).all():
            m = _CORRECTION.match(a.detail or "")
            change = (f"{m.group(1)}: {_grade(m.group(2))} → {_grade(m.group(3))}" if m else (a.detail or ""))
            reason = (m.group(4) or "").strip() if m else ""
            key = (a.actor, reason, a.created_at.replace(second=0, microsecond=0))
            batch = batches.setdefault(key, {"when": a.created_at, "changes": []})
            batch["changes"].append(change)
        for (actor, reason, _), batch in batches.items():
            n = len(batch["changes"])
            title = "Corrección de calificación" if n == 1 else f"Corrección de {n} calificaciones"
            detail = " · ".join(batch["changes"]) + (f" — motivo: {reason}" if reason else "")
            add(batch["when"], "correccion", title, detail, None, actor)

    events.sort(key=lambda e: e["date"])

    current = None
    group = await current_group(session, sid)
    if group is not None:
        term = await session.get(Term, group.term_id)
        plan = await session.get(PlanVersion, group.plan_version_id)
        rvoe = await session.get(Rvoe, plan.rvoe_id) if plan else None
        program = await session.get(Program, rvoe.program_id) if rvoe else None
        current = {
            "period_number": group.period_number, "group_code": group.code,
            "term_name": term.name if term else "", "term_open": bool(term and term.is_open),
            "program": program.name if program else "",
        }
    return {
        "status": student.status.value if hasattr(student.status, "value") else student.status,
        "status_label": STATUS_LABELS.get(str(getattr(student.status, "value", student.status)), ""),
        "current": current,
        "events": events,
    }


__all__ = ["student_history", "uuid"]
