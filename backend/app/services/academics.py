"""Academic business rules: RVOE operability (RT-03), seriación (RF-C07),
kardex and curricular progress (RF-C05/C06/C08), attendance right-to-exam
(RF-A02/A05)."""
import json
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    AttendanceRecord,
    AuditLog,
    AttendanceStatus,
    Campus,
    ClassSession,
    EvaluationComponent,
    EvaluationKind,
    Grade,
    Group,
    GroupEnrollment,
    GroupSubject,
    PlanEnrollmentStatus,
    PlanSubject,
    PlanVersion,
    Program,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    SubjectPrerequisite,
    Term,
)

PASSING_GRADE = 6.0

# audit action of a cambio de RVOE (services/plan_change.py); the kárdex reads it to
# chain the plan that was left with the one it led to
PLAN_CHANGE_ACTION = "plan_enrollment.rvoe_changed"
# audit action of each subject recognized by EQ/REV/CONV; its detail keeps the
# origin (RVOE and subject it comes from, or the external document) shown in the kárdex
RECOGNITION_ACTION = "subject_enrollment.recognized"

# Subjects acreditadas por equivalencia / revalidación / convalidación live in an
# internal group whose code ends with the kind (e.g. "ARQ-014-EQ"); their grade is
# the authority's, not one captured through evaluation components.
RECOGNITION_SUFFIXES = {"-EQ": "eq", "-REV": "rev", "-CONV": "conv"}


def ordinary_grade(
    components: list[EvaluationComponent], captured: dict[uuid.UUID, float]
) -> float | None:
    """Weighted grade of the components that weigh in the final (the ordinario, CF),
    rounded to one decimal; None until every one of them is captured."""
    weighing = [c for c in components if c.weighs_in_final]
    total = sum(c.weight_pct for c in weighing)
    if not weighing or total <= 0 or any(c.id not in captured for c in weighing):
        return None
    return round(sum(captured[c.id] * c.weight_pct for c in weighing) / total, 1)


def recognition_kind(group_code: str) -> str | None:
    code = group_code.upper()
    return next((kind for suffix, kind in RECOGNITION_SUFFIXES.items() if code.endswith(suffix)), None)


def internal_group_clause():
    """SQL condition for those internal recognition groups — kept out of the group
    lists, the SEP export and enrollment counts (nobody attends them)."""
    return or_(*[Group.code.ilike(f"%{suffix}") for suffix in RECOGNITION_SUFFIXES])  # type: ignore[attr-defined]


async def require_operable_rvoe(session: AsyncSession, plan_version_id: uuid.UUID) -> Rvoe:
    """RT-03: block operations under a non-vigente RVOE."""
    plan = await session.get(PlanVersion, plan_version_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan de estudios no encontrado")
    rvoe = await session.get(Rvoe, plan.rvoe_id)
    if rvoe is None or not rvoe.is_operable():
        raise HTTPException(
            status_code=409,
            detail="El RVOE de este plan no está vigente; la operación está bloqueada (RT-03)",
        )
    return rvoe


async def passed_subject_ids(session: AsyncSession, student_id: uuid.UUID) -> set[uuid.UUID]:
    """PlanSubject ids the student has passed (any attempt)."""
    result = await session.exec(
        select(GroupSubject.plan_subject_id)
        .join(SubjectEnrollment, SubjectEnrollment.group_subject_id == GroupSubject.id)
        .where(
            SubjectEnrollment.student_id == student_id,
            SubjectEnrollment.status == SubjectEnrollmentStatus.aprobada,
        )
    )
    return set(result.all())


async def check_prerequisites(
    session: AsyncSession, student_id: uuid.UUID, plan_subject_id: uuid.UUID
) -> list[uuid.UUID]:
    """RF-C07: returns the list of unmet prerequisite subject ids (empty = ok)."""
    result = await session.exec(
        select(SubjectPrerequisite.prerequisite_id).where(
            SubjectPrerequisite.subject_id == plan_subject_id
        )
    )
    required = set(result.all())
    if not required:
        return []
    passed = await passed_subject_ids(session, student_id)
    return sorted(required - passed, key=str)


async def kardex_rows(
    session: AsyncSession, student_id: uuid.UUID, plan_version_id: uuid.UUID
) -> list[dict]:
    """RF-C05: full academic history for a plan enrollment, best grade per subject."""
    result = await session.exec(
        select(SubjectEnrollment, PlanSubject, Group)
        .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
        .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
        .join(Group, Group.id == GroupSubject.group_id)
        .join(GroupEnrollment, GroupEnrollment.id == SubjectEnrollment.group_enrollment_id)
        .where(
            SubjectEnrollment.student_id == student_id,
            PlanSubject.plan_version_id == plan_version_id,
            SubjectEnrollment.status != SubjectEnrollmentStatus.baja,
        )
        .order_by(PlanSubject.period_number, PlanSubject.code, SubjectEnrollment.attempt_number)
    )
    rows = []
    for enrollment, subject, group in result.all():
        rows.append(
            {
                "subject_enrollment_id": str(enrollment.id),
                "plan_subject_id": str(subject.id),
                "code": subject.code,
                "name": subject.name,
                "period_number": subject.period_number,
                "credits": subject.credits,
                "group_code": group.code,
                "attempt_number": enrollment.attempt_number,
                "status": enrollment.status,
                "final_grade": enrollment.final_grade,
            }
        )
    return rows


async def curricular_progress(
    session: AsyncSession, student_id: uuid.UUID, plan_version_id: uuid.UUID
) -> dict:
    """RF-C08: credits earned / total, subject counts, GPA, titulación eligibility."""
    totals = (
        await session.exec(
            select(func.count(PlanSubject.id), func.coalesce(func.sum(PlanSubject.credits), 0.0)).where(
                PlanSubject.plan_version_id == plan_version_id
            )
        )
    ).one()
    total_subjects, total_credits = int(totals[0]), float(totals[1])

    rows = await kardex_rows(session, student_id, plan_version_id)
    passed = {r["plan_subject_id"]: r for r in rows if r["status"] == SubjectEnrollmentStatus.aprobada}
    earned_credits = sum(r["credits"] for r in passed.values())
    grades = [r["final_grade"] for r in passed.values() if r["final_grade"] is not None]
    gpa = round(sum(grades) / len(grades), 2) if grades else None
    return {
        "total_subjects": total_subjects,
        "passed_subjects": len(passed),
        "total_credits": total_credits,
        "earned_credits": earned_credits,
        "credit_progress_pct": round(earned_credits / total_credits * 100, 1) if total_credits else 0.0,
        "gpa": gpa,
        "eligible_for_degree": total_subjects > 0 and len(passed) == total_subjects,
    }


async def student_kardex(
    session: AsyncSession, student_id: uuid.UUID, program_id: uuid.UUID | None = None
) -> dict:
    """One kárdex per student and carrera, across every plan/RVOE of that carrera.

    The kárdex is the current plan's (the inscrito one that started last), because
    the certificate is issued by the last RVOE: `rows` are its subjects — each
    attempt, the ones recognized by EQ/REV/CONV with their `origin` (RVOE and
    subject, or external document), and the ones not taken yet. What was studied
    under earlier plans goes to `previous`, grouped by plan, as the backing of those
    recognitions. Progress is measured against the current plan.

    A plan left through a cambio de RVOE (PLAN_CHANGE_ACTION in the audit log) is
    part of the kárdex of the plan it led to, even in another carrera: one history.
    A student with two active carreras has one kárdex each; `program_id` picks it
    (default: the carrera of the current plan)."""
    plan_enrollments = (
        await session.exec(
            select(StudentPlanEnrollment, Term, Rvoe, Program)
            .join(Term, Term.id == StudentPlanEnrollment.start_term_id)
            .join(PlanVersion, PlanVersion.id == StudentPlanEnrollment.plan_version_id)
            .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
            .join(Program, Program.id == Rvoe.program_id)
            .where(StudentPlanEnrollment.student_id == student_id)
        )
    ).all()
    if not plan_enrollments:
        return {"program_id": None, "programs": [], "current_plan_version_id": None,
                "period_type": None, "periods": [], "rows": [], "previous": [], "progress": None}

    def recency(row):
        return (row[0].status == PlanEnrollmentStatus.inscrito, row[1].start_date)

    # cambio de RVOE links: new plan enrollment -> the one it replaced
    by_id = {row[0].id: row for row in plan_enrollments}
    came_from: dict[uuid.UUID, uuid.UUID] = {}
    for log in (
        await session.exec(
            select(AuditLog).where(
                AuditLog.action == PLAN_CHANGE_ACTION,
                AuditLog.entity_id.in_([str(i) for i in by_id]),  # type: ignore[attr-defined]
            )
        )
    ).all():
        previous = json.loads(log.detail or "{}").get("from_plan_enrollment_id")
        if previous and uuid.UUID(previous) in by_id:
            came_from[uuid.UUID(log.entity_id)] = uuid.UUID(previous)
    replaced = set(came_from.values())
    heads = [row for row in plan_enrollments if row[0].id not in replaced]

    programs: dict[uuid.UUID, str] = {}
    for _, _, _, program in sorted(heads, key=recency, reverse=True):
        programs.setdefault(program.id, program.name)
    if program_id not in programs:
        program_id = next(iter(programs))
    heads = [row for row in heads if row[3].id == program_id]
    line: set[uuid.UUID] = set()
    for head, *_ in heads:
        cursor = head.id
        while cursor is not None and cursor not in line:
            line.add(cursor)
            cursor = came_from.get(cursor)
    line_plan_versions = {by_id[i][0].plan_version_id for i in line}
    current, _, current_rvoe, _ = max(heads, key=recency)
    current_plan = await session.get(PlanVersion, current.plan_version_id)

    taken = (
        await session.exec(
            select(SubjectEnrollment, PlanSubject, Group, Term, Campus, Rvoe)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .join(PlanVersion, PlanVersion.id == PlanSubject.plan_version_id)
            .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
            .join(Group, Group.id == GroupSubject.group_id)
            .join(Term, Term.id == Group.term_id)
            .join(Campus, Campus.id == Group.campus_id)
            .where(
                SubjectEnrollment.student_id == student_id,
                PlanSubject.plan_version_id.in_(line_plan_versions),  # type: ignore[attr-defined]
                SubjectEnrollment.status != SubjectEnrollmentStatus.baja,  # a dropped subject is not part of the record
            )
        )
    ).all()
    rvoe_by_plan = {subject.plan_version_id: rvoe.agreement_number for _, subject, *_, rvoe in taken}
    rvoe_by_plan[current.plan_version_id] = current_rvoe.agreement_number
    taken = [row[:5] for row in taken]

    # grade breakdown: CF from the counting components, E1/E2 from extraordinario
    # and título de suficiencia
    counting: dict[uuid.UUID, list[EvaluationComponent]] = defaultdict(list)
    subject_ids = {ps.id for _, ps, *_ in taken}
    if subject_ids:
        for c in (
            await session.exec(
                select(EvaluationComponent).where(
                    EvaluationComponent.plan_subject_id.in_(subject_ids)  # type: ignore[attr-defined]
                )
            )
        ).all():
            if c.weighs_in_final:
                counting[c.plan_subject_id].append(c)
    captured: dict[uuid.UUID, dict[uuid.UUID, float]] = defaultdict(dict)
    kind_values: dict[uuid.UUID, dict[EvaluationKind, float]] = defaultdict(dict)
    enrollment_ids = [se.id for se, *_ in taken]
    if enrollment_ids:
        for grade, component in (
            await session.exec(
                select(Grade, EvaluationComponent)
                .join(EvaluationComponent, EvaluationComponent.id == Grade.component_id)
                .where(Grade.subject_enrollment_id.in_(enrollment_ids))  # type: ignore[attr-defined]
            )
        ).all():
            captured[grade.subject_enrollment_id][component.id] = grade.value
            kind_values[grade.subject_enrollment_id][component.kind] = grade.value

    rows = []
    for enrollment, subject, group, term, campus in taken:
        recognition = recognition_kind(group.code)
        components = counting.get(subject.id, [])
        values = captured.get(enrollment.id, {})
        cf = None
        if recognition is None:
            cf = ordinary_grade(components, values)
            if cf is None and not values:
                # history loaded without component grades: the final grade is the ordinario
                cf = enrollment.final_grade
        extra = kind_values.get(enrollment.id, {})
        rows.append({
            "row_id": str(enrollment.id),
            "subject_enrollment_id": str(enrollment.id),
            "plan_subject_id": str(subject.id),
            "plan_version_id": str(subject.plan_version_id),
            "rvoe": rvoe_by_plan.get(subject.plan_version_id, ""),
            "code": subject.code,
            "name": subject.name,
            "period_number": subject.period_number,
            "credits": subject.credits,
            "term_name": term.name,
            "term_start": term.start_date.isoformat(),
            "group_code": group.code,
            "campus_name": campus.name,
            "attempt_number": enrollment.attempt_number,
            "status": enrollment.status,
            "final_grade": enrollment.final_grade,
            "cf": cf,
            "e1": extra.get(EvaluationKind.extraordinario),
            "e2": extra.get(EvaluationKind.titulo_suficiencia),
            "recognition": recognition,
        })

    taken_subjects = {subject.id for _, subject, *_ in taken}
    for subject in (
        await session.exec(select(PlanSubject).where(PlanSubject.plan_version_id == current.plan_version_id))
    ).all():
        if subject.id in taken_subjects:
            continue
        rows.append({
            "row_id": f"pendiente:{subject.id}",
            "subject_enrollment_id": None,
            "plan_subject_id": str(subject.id),
            "plan_version_id": str(subject.plan_version_id),
            "rvoe": rvoe_by_plan.get(subject.plan_version_id, ""),
            "code": subject.code,
            "name": subject.name,
            "period_number": subject.period_number,
            "credits": subject.credits,
            "term_name": None,
            "term_start": None,
            "group_code": None,
            "campus_name": None,
            "attempt_number": None,
            "status": "pendiente",
            "final_grade": None,
            "cf": None,
            "e1": None,
            "e2": None,
            "recognition": None,
        })

    rows.sort(key=lambda r: (r["period_number"], r["term_start"] or "9999-12-31", r["code"], r["attempt_number"] or 0))

    # where each EQ/REV/CONV comes from (RVOE and subject, or the external document)
    recognized_ids = [r["subject_enrollment_id"] for r in rows if r["recognition"]]
    origins: dict[str, str] = {}
    if recognized_ids:
        for log in (
            await session.exec(
                select(AuditLog).where(
                    AuditLog.action == RECOGNITION_ACTION,
                    AuditLog.entity_id.in_(recognized_ids),  # type: ignore[attr-defined]
                )
            )
        ).all():
            origins[log.entity_id] = json.loads(log.detail or "{}").get("origin") or ""
    for r in rows:
        r["origin"] = origins.get(r["subject_enrollment_id"] or "")

    # the kárdex is the current (final) plan's: the certificate is issued by its RVOE;
    # what was studied under earlier RVOE goes to `previous`, as the backing of the
    # recognitions
    current_id = str(current.plan_version_id)
    main = [r for r in rows if r["plan_version_id"] == current_id]
    earlier: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["plan_version_id"] != current_id:
            earlier[r["plan_version_id"]].append(r)
    names = {
        str(plan.id): (rvoe.agreement_number, program.name)
        for plan, rvoe, program in (
            await session.exec(
                select(PlanVersion, Rvoe, Program)
                .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
                .join(Program, Program.id == Rvoe.program_id)
                .where(PlanVersion.id.in_([uuid.UUID(i) for i in earlier] or [uuid.uuid4()]))  # type: ignore[attr-defined]
            )
        ).all()
    }
    previous = [
        {"plan_version_id": plan_id, "rvoe": names.get(plan_id, ("", ""))[0],
         "program": names.get(plan_id, ("", ""))[1], "rows": plan_rows}
        for plan_id, plan_rows in sorted(
            earlier.items(), key=lambda kv: min(r["term_start"] or "9999" for r in kv[1])
        )
    ]
    period_numbers = sorted({r["period_number"] for r in main})
    periods = [
        {"period_number": n, "rvoe": current_rvoe.agreement_number, "rvoe_changed": i == 0}
        for i, n in enumerate(period_numbers)
    ]

    return {
        "program_id": str(program_id),
        "programs": [{"id": str(pid), "name": name} for pid, name in programs.items()],
        "current_plan_version_id": current_id,
        "period_type": current_plan.period_type if current_plan else None,
        "periods": periods,
        "rows": main,
        "previous": previous,
        "progress": await curricular_progress(session, student_id, current.plan_version_id),
    }


async def attendance_summary(
    session: AsyncSession, student_id: uuid.UUID, group_subject_id: uuid.UUID
) -> dict:
    """RF-A05/A02: attendance % for a student in a subject and right-to-exam flag.
    presente/retardo/justificado/participacion count as attended."""
    total = (
        await session.exec(
            select(func.count(ClassSession.id)).where(
                ClassSession.group_subject_id == group_subject_id
            )
        )
    ).one()
    attended = (
        await session.exec(
            select(func.count(AttendanceRecord.id))
            .join(ClassSession, ClassSession.id == AttendanceRecord.session_id)
            .where(
                ClassSession.group_subject_id == group_subject_id,
                AttendanceRecord.student_id == student_id,
                AttendanceRecord.status != AttendanceStatus.falta,
            )
        )
    ).one()
    total, attended = int(total), int(attended)
    pct = round(attended / total * 100, 1) if total else 100.0

    group_subject = await session.get(GroupSubject, group_subject_id)
    group = await session.get(Group, group_subject.group_id) if group_subject else None
    plan = await session.get(PlanVersion, group.plan_version_id) if group else None
    min_pct = plan.min_attendance_pct if plan else 80.0
    return {
        "student_id": str(student_id),
        "group_subject_id": str(group_subject_id),
        "sessions": total,
        "attended": attended,
        "attendance_pct": pct,
        "min_attendance_pct": min_pct,
        "right_to_exam": pct >= min_pct,
    }


async def _find_plan_enrollment(
    session: AsyncSession, student_id: uuid.UUID, plan_version_id: uuid.UUID
) -> StudentPlanEnrollment | None:
    return (
        await session.exec(
            select(StudentPlanEnrollment).where(
                StudentPlanEnrollment.student_id == student_id,
                StudentPlanEnrollment.plan_version_id == plan_version_id,
            )
        )
    ).first()


async def active_plan_enrollment(
    session: AsyncSession, student: Student, plan_version_id: uuid.UUID
) -> StudentPlanEnrollment:
    enrollment = await _find_plan_enrollment(session, student.id, plan_version_id)
    if enrollment is None:
        raise HTTPException(
            status_code=404, detail="El alumno no está inscrito en ese plan de estudios"
        )
    return enrollment


async def get_or_create_plan_enrollment(
    session: AsyncSession,
    student: Student,
    plan_version_id: uuid.UUID,
    start_term_id: uuid.UUID,
) -> tuple[StudentPlanEnrollment, bool]:
    """Return the student's plan enrollment, creating it if absent (so enrolling
    into a group is a single act — no separate plan-enrollment step). The bool
    is True when a new enrollment was created."""
    existing = await _find_plan_enrollment(session, student.id, plan_version_id)
    if existing:
        return existing, False
    enrollment = StudentPlanEnrollment(
        student_id=student.id,
        plan_version_id=plan_version_id,
        start_term_id=start_term_id,
    )
    session.add(enrollment)
    await session.flush()
    return enrollment, True
