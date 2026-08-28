"""Egresados (RF-C09 adjacent): who finished, from which plan, in which period,
and whether the título was ever registered.

Nothing writes an "egreso date" today — `Student.status` and
`StudentPlanEnrollment.status` are set by hand, and neither carries a timestamp.
So the period is DERIVED from the last term the student was enrolled in, which
is the same evidence a person would use reading the expediente. When a student
has no enrollment history at all the period is null rather than guessed.
"""
import unicodedata
import uuid
from datetime import date

from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    DegreeRecord,
    Group,
    GroupEnrollment,
    PlanEnrollmentStatus,
    PlanVersion,
    Program,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    StudentStatus,
    Term,
)
from app.models.alumni import (
    AlumniDegree,
    AlumniProgramBucket,
    AlumniRow,
    AlumniStats,
    AlumniTermBucket,
)

# A plan enrollment in either state means the student finished coursework;
# `titulado` additionally means the degree was awarded.
GRADUATED_PLAN_STATES = (PlanEnrollmentStatus.egresado, PlanEnrollmentStatus.titulado)

NO_TERM_LABEL = "Sin periodo"
NO_PLAN_LABEL = "Sin plan"


def _fold(text: str) -> str:
    """Casefold and strip accents — degree records store the program as free
    text ("Licenciatura en Derecho"), so matching one to a plan cannot be
    case- or accent-sensitive."""
    stripped = unicodedata.normalize("NFD", text)
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").casefold().strip()


async def _egreso_terms(
    session: AsyncSession, student_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, Term], dict[uuid.UUID, Term]]:
    """Last term enrolled, keyed BY PLAN ENROLLMENT and, as a fallback, by student.

    The period belongs to the plan, not to the person. A graduate who is now
    studying a maestría must not have their licenciatura dated by the maestría's
    current term — `GroupEnrollment.plan_enrollment_id` carries exactly that
    attribution. The per-student map is only for rows that have no plan
    enrollment to attribute to.

    Reads every (plan enrollment, student, term) triple once and picks the max in
    Python: a per-row MAX would be one query per graduate.
    """
    if not student_ids:
        return {}, {}
    rows = (
        await session.exec(
            select(GroupEnrollment.plan_enrollment_id, GroupEnrollment.student_id, Term)
            .join(Group, Group.id == GroupEnrollment.group_id)
            .join(Term, Term.id == Group.term_id)
            .where(GroupEnrollment.student_id.in_(student_ids))  # type: ignore[attr-defined]
        )
    ).all()
    by_plan: dict[uuid.UUID, Term] = {}
    by_student: dict[uuid.UUID, Term] = {}
    for plan_enrollment_id, student_id, term in rows:
        for bucket, key in ((by_plan, plan_enrollment_id), (by_student, student_id)):
            current = bucket.get(key)
            if current is None or term.end_date > current.end_date:
                bucket[key] = term
    return by_plan, by_student


async def _degrees(
    session: AsyncSession, student_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DegreeRecord]]:
    if not student_ids:
        return {}
    records = (
        await session.exec(
            select(DegreeRecord)
            .where(DegreeRecord.student_id.in_(student_ids))  # type: ignore[attr-defined]
            .order_by(DegreeRecord.issue_date)
        )
    ).all()
    out: dict[uuid.UUID, list[DegreeRecord]] = {}
    for record in records:
        out.setdefault(record.student_id, []).append(record)
    return out


def _match_degree(
    records: list[DegreeRecord], program_name: str | None
) -> DegreeRecord | None:
    """The degree registered for THIS program.

    `DegreeRecord.program_name` is free text with no FK, so the match is by
    folded name — and ONLY by folded name. There is deliberately no "the student
    has just one degree, it must be this one" fallback: a diplomado, or the
    título from the other plan they finished, would then certify a program nobody
    certified them in. This is an official registry; under-claiming titulación is
    recoverable, over-claiming it is not.
    """
    if not program_name:
        return None
    wanted = _fold(program_name)
    for record in records:
        if _fold(record.program_name) == wanted:
            return record
    return None


async def alumni_rows(
    session: AsyncSession,
    *,
    scope: list[uuid.UUID] | None = None,
    campus_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    titulado: bool | None = None,
    q: str | None = None,
) -> list[AlumniRow]:
    """Every graduate visible in `scope`, one row per finished program.

    The cohort is deliberately the union of two signals — a plan enrollment in
    egresado/titulado, OR the student themselves marked egresado — because
    nothing keeps the two in step today and either one alone would under-count.
    """
    query = (
        select(Student, StudentPlanEnrollment, PlanVersion, Rvoe, Program)
        .join(
            StudentPlanEnrollment,
            StudentPlanEnrollment.student_id == Student.id,  # type: ignore[arg-type]
            isouter=True,
        )
        .join(
            PlanVersion,
            PlanVersion.id == StudentPlanEnrollment.plan_version_id,  # type: ignore[arg-type]
            isouter=True,
        )
        .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id, isouter=True)  # type: ignore[arg-type]
        .join(Program, Program.id == Rvoe.program_id, isouter=True)  # type: ignore[arg-type]
        .where(
            or_(
                Student.status == StudentStatus.egresado,
                StudentPlanEnrollment.status.in_(GRADUATED_PLAN_STATES),  # type: ignore[union-attr]
            )
        )
        .order_by(Student.full_name)
    )
    if scope is not None:
        query = query.where(Student.campus_id.in_(scope))  # type: ignore[attr-defined]
    if campus_id:
        query = query.where(Student.campus_id == campus_id)
    if q:
        like = f"%{q.upper()}%"
        query = query.where(
            (Student.curp.like(like))  # type: ignore[attr-defined]
            | (Student.full_name.ilike(f"%{q}%"))  # type: ignore[attr-defined]
            | (Student.enrollment_number.like(like))  # type: ignore[attr-defined]
        )

    records = (await session.exec(query)).all()
    # A student still enrolled in a second plan shows up twice: once for the plan
    # they finished, once for the one they are in. Only the finished one is an
    # alumni row — unless the plan side says nothing at all, which is the
    # "marked egresado by hand" case the outer join is there to keep.
    rows_by_student: dict[uuid.UUID, list[tuple]] = {}
    for student, plan_enrollment, plan, rvoe, program in records:
        rows_by_student.setdefault(student.id, []).append(
            (student, plan_enrollment, plan, rvoe, program)
        )
    kept: list[tuple] = []
    for candidates in rows_by_student.values():
        graduated = [c for c in candidates if c[1] is not None and c[1].status in GRADUATED_PLAN_STATES]
        if graduated:
            kept.extend(graduated)
        elif len(candidates) == 1 and candidates[0][1] is None:
            kept.append(candidates[0])  # egresado with no plan enrollment at all
        else:
            # Marked egresado at the student level while every plan enrollment
            # still reads inscrito: attribute it to the plans they actually hold.
            kept.extend(candidates)

    student_ids = [c[0].id for c in kept]
    terms_by_plan, terms_by_student = await _egreso_terms(session, student_ids)
    degrees = await _degrees(session, student_ids)

    out: list[AlumniRow] = []
    for student, plan_enrollment, plan, rvoe, program in kept:
        # A plan with no group enrollments of its own has no derivable period;
        # borrowing the student's latest term would date it from another plan.
        term = (
            terms_by_plan.get(plan_enrollment.id)
            if plan_enrollment is not None
            else terms_by_student.get(student.id)
        )
        degree = _match_degree(degrees.get(student.id, []), program.name if program else None)
        is_titulado = (
            plan_enrollment is not None
            and plan_enrollment.status == PlanEnrollmentStatus.titulado
        ) or degree is not None
        out.append(
            AlumniRow(
                student_id=student.id,
                enrollment_number=student.enrollment_number,
                full_name=student.full_name,
                curp=student.curp,
                email=student.email,
                campus_id=student.campus_id,
                student_status=student.status,
                has_photo=student.has_photo,
                plan_enrollment_id=plan_enrollment.id if plan_enrollment else None,
                plan_enrollment_status=plan_enrollment.status if plan_enrollment else None,
                program_id=program.id if program else None,
                program_name=program.name if program else None,
                level=program.level if program else None,
                plan_version_label=plan.version_label if plan else None,
                rvoe=rvoe.agreement_number if rvoe else None,
                egreso_term_id=term.id if term else None,
                egreso_term_name=term.name if term else None,
                egreso_date=term.end_date if term else None,
                titulado=is_titulado,
                degree=(
                    AlumniDegree(
                        kind=degree.kind,
                        folio=degree.folio,
                        issue_date=degree.issue_date,
                        program_name=degree.program_name,
                    )
                    if degree
                    else None
                ),
            )
        )

    # These filter AFTER the per-student reduction above, never in SQL. term_id
    # has to, because the period is derived. program_id has to for a subtler
    # reason: pruning rows in SQL changes which candidates the reduction sees, so
    # a student whose OTHER plan is the graduated one would come back as an
    # egresado of the program they are merely still enrolled in.
    if program_id is not None:
        out = [r for r in out if r.program_id == program_id]
    if term_id is not None:
        out = [r for r in out if r.egreso_term_id == term_id]
    if titulado is not None:
        out = [r for r in out if r.titulado is titulado]
    # Newest period first (that is the useful order for a graduate registry);
    # rows with no derivable period sort last instead of disappearing.
    out.sort(key=lambda r: (r.egreso_date or date.min, r.full_name), reverse=True)
    return out


def alumni_stats(rows: list[AlumniRow]) -> AlumniStats:
    """Aggregates over rows already fetched — the dashboard and the table must
    never disagree, so they are computed from the same list rather than from two
    queries that could drift apart."""
    students = {r.student_id for r in rows}
    titulados = {r.student_id for r in rows if r.titulado}

    by_term: dict[uuid.UUID | None, AlumniTermBucket] = {}
    for row in rows:
        bucket = by_term.get(row.egreso_term_id)
        if bucket is None:
            bucket = AlumniTermBucket(
                term_id=row.egreso_term_id,
                term_name=row.egreso_term_name or NO_TERM_LABEL,
                end_date=row.egreso_date,
                egresados=0,
                titulados=0,
            )
            by_term[row.egreso_term_id] = bucket
        bucket.egresados += 1
        bucket.titulados += 1 if row.titulado else 0

    by_program: dict[uuid.UUID | None, AlumniProgramBucket] = {}
    for row in rows:
        bucket = by_program.get(row.program_id)
        if bucket is None:
            bucket = AlumniProgramBucket(
                program_id=row.program_id,
                program_name=row.program_name or NO_PLAN_LABEL,
                level=row.level,
                egresados=0,
                titulados=0,
            )
            by_program[row.program_id] = bucket
        bucket.egresados += 1
        bucket.titulados += 1 if row.titulado else 0

    return AlumniStats(
        egresados=len(students),
        titulados=len(titulados),
        titulacion_pct=round(len(titulados) / len(students) * 100, 1) if students else 0.0,
        rows=len(rows),
        # Distinct students, to stay comparable with `egresados` above: the UI
        # prints these two right under that card, and a row count there could
        # read larger than the population it describes.
        sin_periodo=len({r.student_id for r in rows if r.egreso_term_id is None}),
        sin_plan=len({r.student_id for r in rows if r.plan_enrollment_id is None}),
        # Oldest period first so the dashboard reads left-to-right as a timeline;
        # the undated bucket sorts last instead of being dropped.
        by_term=sorted(by_term.values(), key=lambda b: b.end_date or date.min),
        by_program=sorted(by_program.values(), key=lambda b: -b.egresados),
    )
