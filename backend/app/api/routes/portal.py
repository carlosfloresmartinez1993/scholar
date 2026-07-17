"""Student portal (servo parity): a role=alumno account reads ITS OWN info —
enrollment summary, kardex, current grades, account statement and schedule.
Strictly read-only and self-scoped: every query keys off the linked student_id;
staff accounts never pass CurrentStudentUser (and alumno never passes the
staff guards in api/deps.py)."""
import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import CurrentStudentUser, SessionDep
from app.api.routes.students import schedule_payload
from app.models import (
    AccountStatement,
    Group,
    GroupEnrollment,
    GroupEnrollmentStatus,
    PlanSubject,
    PlanVersion,
    Program,
    GroupSubject,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    StudentPublic,
    SubjectEnrollment,
    Term,
)
from app.services.academics import curricular_progress, kardex_rows
from app.services.treasury import build_account_statement

router = APIRouter(prefix="/portal", tags=["portal"])


async def _linked_student(session: SessionDep, current_user: CurrentStudentUser) -> Student:
    student = await session.get(Student, current_user.student_id)
    if student is None:  # orphaned link — should not happen
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return student


async def _plan_enrollments(
    session: SessionDep, student_id: uuid.UUID
) -> list[StudentPlanEnrollment]:
    # newest first so "first active" is deterministic with multiple plans
    return (
        await session.exec(
            select(StudentPlanEnrollment)
            .where(StudentPlanEnrollment.student_id == student_id)
            .order_by(StudentPlanEnrollment.created_at.desc())  # type: ignore[attr-defined]
        )
    ).all()


@router.get("/me")
async def portal_me(session: SessionDep, current_user: CurrentStudentUser) -> dict:
    """Student data + a compact enrollment summary (plan / programa / grupo)."""
    student = await _linked_student(session, current_user)
    enrollments = await _plan_enrollments(session, student.id)
    active_plan = next(
        (e for e in enrollments if e.status == "inscrito"),
        enrollments[0] if enrollments else None,
    )
    plan_info = None
    if active_plan:
        plan = await session.get(PlanVersion, active_plan.plan_version_id)
        rvoe = await session.get(Rvoe, plan.rvoe_id) if plan else None
        program = await session.get(Program, rvoe.program_id) if rvoe else None
        plan_info = {
            "plan_version_id": str(active_plan.plan_version_id),
            "plan_label": plan.version_label if plan else None,
            "program": program.name if program else None,
            "rvoe": rvoe.agreement_number if rvoe else None,
        }
    row = (
        await session.exec(
            select(GroupEnrollment, Group, Term)
            .join(Group, Group.id == GroupEnrollment.group_id)
            .join(Term, Term.id == Group.term_id)
            .where(
                GroupEnrollment.student_id == student.id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
            )
            .order_by(GroupEnrollment.created_at.desc())  # type: ignore[attr-defined]
        )
    ).first()
    group_info = (
        {"code": row[1].code, "term": row[2].name, "period_number": row[1].period_number}
        if row
        else None
    )
    return {
        "student": StudentPublic.model_validate(student).model_dump(mode="json"),
        "plan": plan_info,
        "group": group_info,
    }


@router.get("/kardex")
async def portal_kardex(
    session: SessionDep,
    current_user: CurrentStudentUser,
    plan_version_id: uuid.UUID | None = None,
) -> dict:
    """Same shape as the staff kardex, restricted to the linked student. The
    plan defaults to the student's active plan enrollment."""
    student = await _linked_student(session, current_user)
    if plan_version_id is None:
        enrollments = await _plan_enrollments(session, student.id)
        active = next(
            (e for e in enrollments if e.status == "inscrito"),
            enrollments[0] if enrollments else None,
        )
        if active is None:
            raise HTTPException(status_code=404, detail="Sin plan de estudios")
        plan_version_id = active.plan_version_id
    else:
        # a student can only ask for kardex of plans they are enrolled in
        own = {e.plan_version_id for e in await _plan_enrollments(session, student.id)}
        if plan_version_id not in own:
            raise HTTPException(status_code=403, detail="Not enough privileges")
    rows = await kardex_rows(session, student.id, plan_version_id)
    progress = await curricular_progress(session, student.id, plan_version_id)
    return {"student_id": str(student.id), "plan_version_id": str(plan_version_id),
            "rows": rows, "progress": progress}


@router.get("/grades")
async def portal_grades(
    session: SessionDep, current_user: CurrentStudentUser
) -> list[dict]:
    """Subjects + grades of the student's ACTIVE group enrollments in open terms."""
    student = await _linked_student(session, current_user)
    rows = (
        await session.exec(
            select(SubjectEnrollment, PlanSubject, Group)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
            .join(
                GroupEnrollment,
                GroupEnrollment.id == SubjectEnrollment.group_enrollment_id,
            )
            .join(Group, Group.id == GroupEnrollment.group_id)
            .join(Term, Term.id == Group.term_id)
            .where(
                SubjectEnrollment.student_id == student.id,
                GroupEnrollment.status == GroupEnrollmentStatus.activa,
                Term.is_open == True,  # noqa: E712
            )
            .order_by(PlanSubject.code)
        )
    ).all()
    return [
        {
            "subject": subject.name,
            "code": subject.code,
            "credits": subject.credits,
            "group_code": group.code,
            "status": enrollment.status,
            "final_grade": enrollment.final_grade,
            "attempt_number": enrollment.attempt_number,
        }
        for enrollment, subject, group in rows
    ]


@router.get("/statement")
async def portal_statement(
    session: SessionDep, current_user: CurrentStudentUser
) -> AccountStatement:
    student = await _linked_student(session, current_user)
    return await build_account_statement(session, student.id)


@router.get("/schedule")
async def portal_schedule(
    session: SessionDep, current_user: CurrentStudentUser
) -> dict:
    student = await _linked_student(session, current_user)
    return await schedule_payload(session, student.id)
