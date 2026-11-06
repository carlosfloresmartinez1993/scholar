"""Academic business rules: RVOE operability (RT-03), seriación (RF-C07),
kardex and curricular progress (RF-C05/C06/C08), attendance right-to-exam
(RF-A02/A05)."""
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlmodel import func, select
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
    GroupSubject,
    PlanEnrollmentStatus,
    PlanSubject,
    PlanVersion,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    SubjectEnrollmentStatus,
    SubjectPrerequisite,
    Term,
)

PASSING_GRADE = 6.0

# Subjects acreditadas por equivalencia / revalidación / convalidación live in an
# internal group whose code ends with the kind (e.g. "ARQ-014-EQ"); their grade is
# the authority's, not one captured through evaluation components.
RECOGNITION_SUFFIXES = {"-EQ": "eq", "-REV": "rev", "-CONV": "conv"}


def recognition_kind(group_code: str) -> str | None:
    code = group_code.upper()
    return next((kind for suffix, kind in RECOGNITION_SUFFIXES.items() if code.endswith(suffix)), None)


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


async def student_kardex(session: AsyncSession, student_id: uuid.UUID) -> dict:
    """One kárdex per student across every plan/RVOE they have been enrolled in.

    Rows are every subject enrollment (each attempt, each plan) plus the subjects of
    the current plan not yet taken. Each row carries the RVOE it was taken under, so
    a plan/RVOE change shows up as the RVOE changing between rows. Progress is
    measured against the current plan: the inscrito one that started last."""
    plan_enrollments = (
        await session.exec(
            select(StudentPlanEnrollment, Term)
            .join(Term, Term.id == StudentPlanEnrollment.start_term_id)
            .where(StudentPlanEnrollment.student_id == student_id)
        )
    ).all()
    if not plan_enrollments:
        return {"current_plan_version_id": None, "period_type": None, "rows": [], "progress": None}
    current, _ = max(
        plan_enrollments,
        key=lambda pe_term: (pe_term[0].status == PlanEnrollmentStatus.inscrito, pe_term[1].start_date),
    )
    current_plan = await session.get(PlanVersion, current.plan_version_id)

    taken = (
        await session.exec(
            select(SubjectEnrollment, PlanSubject, Group, Term, Campus)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .join(Group, Group.id == GroupSubject.group_id)
            .join(Term, Term.id == Group.term_id)
            .join(Campus, Campus.id == Group.campus_id)
            .where(SubjectEnrollment.student_id == student_id)
        )
    ).all()

    plan_ids = {pe.plan_version_id for pe, _ in plan_enrollments} | {ps.plan_version_id for _, ps, *_ in taken}
    rvoe_by_plan = {
        plan.id: rvoe.agreement_number
        for plan, rvoe in (
            await session.exec(
                select(PlanVersion, Rvoe)
                .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
                .where(PlanVersion.id.in_(plan_ids))  # type: ignore[attr-defined]
            )
        ).all()
    }

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
            if c.counts_towards_final:
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
            if components and all(c.id in values for c in components):
                weight = sum(c.weight_pct for c in components)
                if weight > 0:
                    cf = round(sum(values[c.id] * c.weight_pct for c in components) / weight, 1)
            elif not values:
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
    return {
        "current_plan_version_id": str(current.plan_version_id),
        "period_type": current_plan.period_type if current_plan else None,
        "rows": rows,
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
