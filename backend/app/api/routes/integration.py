"""Integration API for the calendar system — calendar.inue.online (RT-11,
RF-I01/I02). Read-only, authenticated with X-API-Key. The scholar system stays
the single source of truth; the calendar consumes groups, schedules,
enrollments and evaluation periods."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep, verify_integration_api_key
from app.models import (
    Group,
    GroupSubject,
    PlanSubject,
    PlanVersion,
    Program,
    Rvoe,
    Student,
    SubjectEnrollment,
    Term,
    User,
)

router = APIRouter(
    prefix="/integration",
    tags=["integration"],
    dependencies=[Depends(verify_integration_api_key)],
)


@router.get("/terms")
async def integration_terms(session: SessionDep) -> list[dict]:
    """Terms + evaluation windows (RF-I01: periodos de evaluación)."""
    terms = (await session.exec(select(Term).order_by(Term.start_date.desc()))).all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "period_type": t.period_type,
            "start_date": t.start_date.isoformat(),
            "end_date": t.end_date.isoformat(),
            "is_open": t.is_open,
            "grade_capture_open": t.grade_capture_open,
        }
        for t in terms
    ]


@router.get("/groups")
async def integration_groups(session: SessionDep, term_id: uuid.UUID | None = None) -> list[dict]:
    """Groups with program/RVOE context and their subjects (RF-I01)."""
    q = (
        select(Group, PlanVersion, Rvoe, Program)
        .join(PlanVersion, PlanVersion.id == Group.plan_version_id)
        .join(Rvoe, Rvoe.id == PlanVersion.rvoe_id)
        .join(Program, Program.id == Rvoe.program_id)
        .order_by(Group.code)
    )
    if term_id:
        q = q.where(Group.term_id == term_id)
    rows = (await session.exec(q)).all()
    out = []
    for group, plan, rvoe, program in rows:
        subjects = (
            await session.exec(
                select(GroupSubject, PlanSubject, User)
                .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
                .outerjoin(User, User.id == GroupSubject.teacher_user_id)
                .where(GroupSubject.group_id == group.id)
            )
        ).all()
        out.append(
            {
                "id": str(group.id),
                "code": group.code,
                "term_id": str(group.term_id),
                "campus_id": str(group.campus_id),
                "period_number": group.period_number,
                "program": program.name,
                "program_level": program.level,
                "modality": rvoe.modality,
                "rvoe": rvoe.agreement_number,
                "plan_version": plan.version_label,
                "subjects": [
                    {
                        "group_subject_id": str(gs.id),
                        "code": ps.code,
                        "name": ps.name,
                        "credits": ps.credits,
                        "schedule_text": gs.schedule_text,
                        "teacher_name": teacher.full_name if teacher else None,
                        "teacher_email": teacher.email if teacher else None,
                    }
                    for gs, ps, teacher in subjects
                ],
            }
        )
    return out


@router.get("/groups/{group_id}/enrollments")
async def integration_group_enrollments(session: SessionDep, group_id: uuid.UUID) -> list[dict]:
    """Students enrolled per subject of a group (RF-I02)."""
    if await session.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    rows = (
        await session.exec(
            select(SubjectEnrollment, GroupSubject, Student)
            .join(GroupSubject, GroupSubject.id == SubjectEnrollment.group_subject_id)
            .join(Student, Student.id == SubjectEnrollment.student_id)
            .where(GroupSubject.group_id == group_id)
        )
    ).all()
    return [
        {
            "group_subject_id": str(gs.id),
            "student_id": str(s.id),
            "curp": s.curp,
            "enrollment_number": s.enrollment_number,
            "full_name": s.full_name,
            "email": s.email,
            "status": e.status,
        }
        for e, gs, s in rows
    ]
