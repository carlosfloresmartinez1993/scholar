"""Academic business rules: RVOE operability (RT-03), seriación (RF-C07),
kardex and curricular progress (RF-C05/C06/C08), attendance right-to-exam
(RF-A02/A05)."""
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlmodel import and_, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    AttendanceRecord,
    AttendanceStatus,
    Campus,
    ClassSession,
    EvaluationComponent,
    EvaluationKind,
    Grade,
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    GroupSubject,
    PlanChange,
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
    SubjectRecognition,
    Term,
)

PASSING_GRADE = 6.0

# audit action of a cambio de RVOE (services/plan_change.py); the kárdex reads it to
# audit log entries, history only: nothing is read back from them (the data lives in
# plan_changes and subject_recognitions)
PLAN_CHANGE_ACTION = "plan_enrollment.rvoe_changed"
RECOGNITION_ACTION = "subject_enrollment.recognized"
PLAN_CHANGE_REVERTED_ACTION = "plan_enrollment.rvoe_change_reverted"

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


async def active_plan_changes(session: AsyncSession, plan_enrollment_ids: list) -> list[PlanChange]:
    """Cambios de RVOE that led to these plan enrollments and were not reverted,
    oldest first."""
    return (
        await session.exec(
            select(PlanChange)
            .where(
                PlanChange.to_plan_enrollment_id.in_(plan_enrollment_ids),  # type: ignore[union-attr]
                PlanChange.reverted_at.is_(None),  # type: ignore[union-attr]
            )
            .order_by(PlanChange.created_at)
        )
    ).all()


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


def _settled_query():
    """(student, plan subject) settled: passed in any attempt, or recognized by
    EQ/REV/CONV even while the grade is pending (the authority's dictamen stands)."""
    return (
        select(SubjectEnrollment.student_id, GroupSubject.plan_subject_id)
        .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
        .join(Group, Group.id == GroupSubject.group_id)
        .where(
            or_(
                SubjectEnrollment.status == SubjectEnrollmentStatus.aprobada,
                and_(SubjectEnrollment.status == SubjectEnrollmentStatus.cursando, internal_group_clause()),
            ),
        )
    )


async def passed_subject_ids(session: AsyncSession, student_id: uuid.UUID) -> set[uuid.UUID]:
    """PlanSubject ids the student has settled."""
    result = await session.exec(_settled_query().where(SubjectEnrollment.student_id == student_id))
    return {subject_id for _, subject_id in result.all()}


async def settled_subjects_of(session: AsyncSession, students) -> dict[uuid.UUID, set[uuid.UUID]]:
    """The same for many students at once; `students` is a subquery of their ids."""
    settled: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for student_id, subject_id in (
        await session.exec(_settled_query().where(SubjectEnrollment.student_id.in_(students)))  # type: ignore[attr-defined]
    ).all():
        settled[student_id].add(subject_id)
    return settled


def _current_group_query():
    """Active groups of the plans in course, the highest cuatrimestre first. A lower
    one is a recursamiento; recognized subjects (internal groups) say nothing about
    where the student is."""
    return (
        select(GroupEnrollment.student_id, Group)
        .join(GroupEnrollment, GroupEnrollment.group_id == Group.id)
        .join(StudentPlanEnrollment, StudentPlanEnrollment.id == GroupEnrollment.plan_enrollment_id)
        .where(
            GroupEnrollment.status == GroupEnrollmentStatus.activa,
            GroupEnrollment.subjects_only == False,  # noqa: E712 — a subject taken in another group
            StudentPlanEnrollment.status == PlanEnrollmentStatus.inscrito,
            ~internal_group_clause(),
        )
        .order_by(Group.period_number.desc(), GroupEnrollment.created_at.desc())  # type: ignore[attr-defined]
    )


async def current_group(
    session: AsyncSession, student_id: uuid.UUID, plan_version_id: uuid.UUID | None = None
) -> Group | None:
    """The group the student really is in: the active one of the highest cuatrimestre
    (of that plan, or of the plans in course)."""
    query = _current_group_query().where(GroupEnrollment.student_id == student_id)
    if plan_version_id is not None:
        query = query.where(Group.plan_version_id == plan_version_id)
    row = (await session.exec(query)).first()
    return row[1] if row else None


async def current_groups_of(session: AsyncSession, students) -> dict[tuple, Group]:
    """(student, plan version) -> their group, for many students at once."""
    groups: dict[tuple, Group] = {}
    for student_id, group in (
        await session.exec(_current_group_query().where(GroupEnrollment.student_id.in_(students)))  # type: ignore[attr-defined]
    ).all():
        groups.setdefault((student_id, group.plan_version_id), group)
    return groups


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

    A plan left through a cambio de RVOE (plan_changes, not reverted) is
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
                "period_type": None, "periods": [], "rows": [], "previous": [], "progress": None,
                "rvoe_change": None}

    def recency(row):
        return (row[0].status == PlanEnrollmentStatus.inscrito, row[1].start_date)

    # cambio de RVOE links: new plan enrollment -> the one it replaced
    by_id = {row[0].id: row for row in plan_enrollments}
    came_from: dict[uuid.UUID, uuid.UUID] = {}
    last_change: dict[uuid.UUID, PlanChange] = {}
    for change in await active_plan_changes(session, list(by_id)):
        if change.from_plan_enrollment_id in by_id:
            came_from[change.to_plan_enrollment_id] = change.from_plan_enrollment_id
            last_change[change.to_plan_enrollment_id] = change
    replaced = set(came_from.values())
    # (a plan the student came back to is replaced and current at once)
    heads = [row for row in plan_enrollments
             if row[0].id not in replaced or row[0].status == PlanEnrollmentStatus.inscrito]

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
        for recognition in (
            await session.exec(
                select(SubjectRecognition).where(
                    SubjectRecognition.subject_enrollment_id.in_(  # type: ignore[attr-defined]
                        [uuid.UUID(i) for i in recognized_ids]
                    )
                )
            )
        ).all():
            origins[str(recognition.subject_enrollment_id)] = recognition.origin
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
    change = last_change.get(current.id)
    rvoe_change = None
    if change is not None and current.status == PlanEnrollmentStatus.inscrito:
        source = by_id[came_from[current.id]]
        rvoe_change = {
            "change_id": str(change.id), "from_rvoe": source[2].agreement_number,
            "from_program": source[3].name, "to_rvoe": current_rvoe.agreement_number,
            "changed_at": change.created_at.isoformat(),
        }
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
        "rvoe_change": rvoe_change,
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
