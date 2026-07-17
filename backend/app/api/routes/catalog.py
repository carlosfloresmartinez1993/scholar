"""Catalog routes: institution, campuses, programs, RVOE, plan versions,
subjects (+seriación, evaluation schemes), terms and groups."""
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.api.deps import AcademicStaff, AnyStaff, ServiciosEscolares, SessionDep
from app.models import (
    Campus,
    CampusCreate,
    CampusPublic,
    CampusUpdate,
    EvaluationComponent,
    EvaluationComponentCreate,
    EvaluationComponentPublic,
    Group,
    GroupCreate,
    GroupPublic,
    GroupSubject,
    GroupSubjectCreate,
    GroupSubjectPublic,
    GroupUpdate,
    Institution,
    InstitutionPublic,
    InstitutionUpdate,
    PlanSubject,
    PlanSubjectCreate,
    PlanSubjectPublic,
    PlanVersion,
    PlanVersionCreate,
    PlanVersionPublic,
    Program,
    ProgramCreate,
    ProgramPublic,
    ProgramUpdate,
    Rvoe,
    RvoeCreate,
    RvoePublic,
    RvoeUpdate,
    SubjectPrerequisite,
    Term,
    TermCreate,
    TermImport,
    TermPublic,
    TermUpdate,
)
from app.services import audit, calendar
from app.services.academics import require_operable_rvoe

router = APIRouter(prefix="/catalog", tags=["catalog"])


async def get_default_institution(session: SessionDep) -> Institution:
    institution = (await session.exec(select(Institution))).first()
    if institution is None:
        raise HTTPException(status_code=500, detail="No hay institución configurada")
    return institution


# --- Institution --------------------------------------------------------------

@router.get("/institution")
async def get_institution(session: SessionDep, _: AnyStaff) -> InstitutionPublic:
    return await get_default_institution(session)


@router.patch("/institution")
async def update_institution(
    session: SessionDep, current_user: ServiciosEscolares, body: InstitutionUpdate
) -> InstitutionPublic:
    institution = await get_default_institution(session)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(institution, k, v)
    session.add(institution)
    audit.record(session, actor=current_user.email, action="institution.updated",
                 entity="institution", entity_id=str(institution.id))
    await session.commit()
    await session.refresh(institution)
    return institution


# --- Campuses ------------------------------------------------------------------

@router.get("/campuses")
async def list_campuses(session: SessionDep, _: AnyStaff) -> list[CampusPublic]:
    return (await session.exec(select(Campus).order_by(Campus.name))).all()


@router.post("/campuses", status_code=201)
async def create_campus(
    session: SessionDep, current_user: ServiciosEscolares, body: CampusCreate
) -> CampusPublic:
    institution_id = body.institution_id or (await get_default_institution(session)).id
    campus = Campus(**body.model_dump(exclude={"institution_id"}), institution_id=institution_id)
    session.add(campus)
    audit.record(session, actor=current_user.email, action="campus.created",
                 entity="campus", entity_id=str(campus.id), detail=campus.name)
    await session.commit()
    await session.refresh(campus)
    return campus


@router.patch("/campuses/{campus_id}")
async def update_campus(
    session: SessionDep, current_user: ServiciosEscolares, campus_id: uuid.UUID,
    body: CampusUpdate,
) -> CampusPublic:
    campus = await session.get(Campus, campus_id)
    if campus is None:
        raise HTTPException(status_code=404, detail="Campus no encontrado")
    data = body.model_dump(exclude_unset=True)
    # reject a link to a campus that doesn't exist in the calendar registry
    # (null clears the link and skips the check)
    if data.get("calendar_campus_id") is not None:
        valid = {c["id"] for c in await calendar.get_campuses()}
        if str(data["calendar_campus_id"]) not in valid:
            raise HTTPException(status_code=422, detail="Campus del calendario no encontrado")
    for k, v in data.items():
        setattr(campus, k, v)
    session.add(campus)
    audit.record(session, actor=current_user.email, action="campus.updated",
                 entity="campus", entity_id=str(campus_id))
    await session.commit()
    await session.refresh(campus)
    return campus


# --- Programs ------------------------------------------------------------------

@router.get("/programs")
async def list_programs(session: SessionDep, _: AnyStaff) -> list[ProgramPublic]:
    return (await session.exec(select(Program).order_by(Program.name))).all()


@router.post("/programs", status_code=201)
async def create_program(
    session: SessionDep, current_user: ServiciosEscolares, body: ProgramCreate
) -> ProgramPublic:
    institution = await get_default_institution(session)
    program = Program(**body.model_dump(), institution_id=institution.id)
    session.add(program)
    audit.record(session, actor=current_user.email, action="program.created",
                 entity="program", entity_id=str(program.id), detail=program.name)
    await session.commit()
    await session.refresh(program)
    return program


@router.patch("/programs/{program_id}")
async def update_program(
    session: SessionDep,
    current_user: ServiciosEscolares,
    program_id: uuid.UUID,
    body: ProgramUpdate,
) -> ProgramPublic:
    program = await session.get(Program, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Programa no encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(program, k, v)
    session.add(program)
    audit.record(session, actor=current_user.email, action="program.updated",
                 entity="program", entity_id=str(program_id))
    await session.commit()
    await session.refresh(program)
    return program


# --- Calendar system (calendar.inue.online) — linking catalogs ------------------

@router.get("/calendar/campuses")
async def list_calendar_campuses(_: AnyStaff) -> list[dict]:
    """Campuses of the calendar system (to link Campus.calendar_campus_id)."""
    return await calendar.get_campuses()


@router.get("/calendar/programs")
async def list_calendar_programs(_: AnyStaff) -> list[dict]:
    """Programs of the calendar system (to link Program.calendar_program_id)."""
    return await calendar.get_programs()


@router.get("/calendar/terms")
async def list_calendar_terms(session: SessionDep, _: AnyStaff) -> list[dict]:
    """Terms of the calendar system, flagged with whether they're already imported
    into scholar — so staff import a period instead of retyping its dates."""
    terms = await calendar.get_terms()
    imported = set(
        (
            await session.exec(
                select(Term.calendar_term_id).where(Term.calendar_term_id.is_not(None))  # type: ignore[union-attr]
            )
        ).all()
    )
    for t in terms:
        t["imported"] = str(t.get("id")) in {str(i) for i in imported}
    return terms


@router.get("/calendar/groups")
async def list_calendar_groups(
    _: AnyStaff,
    term_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
) -> list[dict]:
    """Groups of the calendar system (to link Group.calendar_group_id)."""
    return await calendar.get_groups(term_id=term_id, program_id=program_id)


# --- RVOE (RT-01/02/03) ---------------------------------------------------------

@router.get("/rvoes")
async def list_rvoes(
    session: SessionDep, _: AnyStaff, program_id: uuid.UUID | None = None
) -> list[RvoePublic]:
    q = select(Rvoe).order_by(Rvoe.created_at)
    if program_id:
        q = q.where(Rvoe.program_id == program_id)
    return (await session.exec(q)).all()


@router.post("/rvoes", status_code=201)
async def create_rvoe(
    session: SessionDep, current_user: ServiciosEscolares, body: RvoeCreate
) -> RvoePublic:
    if await session.get(Program, body.program_id) is None:
        raise HTTPException(status_code=404, detail="Programa no encontrado")
    if await session.get(Campus, body.campus_id) is None:
        raise HTTPException(status_code=404, detail="Plantel no encontrado")
    dup = (
        await session.exec(select(Rvoe).where(Rvoe.agreement_number == body.agreement_number))
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="Ya existe un RVOE con ese número de acuerdo")
    rvoe = Rvoe(**body.model_dump())
    session.add(rvoe)
    audit.record(session, actor=current_user.email, action="rvoe.created",
                 entity="rvoe", entity_id=str(rvoe.id), detail=rvoe.agreement_number)
    await session.commit()
    await session.refresh(rvoe)
    return rvoe


@router.patch("/rvoes/{rvoe_id}")
async def update_rvoe(
    session: SessionDep, current_user: ServiciosEscolares, rvoe_id: uuid.UUID, body: RvoeUpdate
) -> RvoePublic:
    rvoe = await session.get(Rvoe, rvoe_id)
    if rvoe is None:
        raise HTTPException(status_code=404, detail="RVOE no encontrado")
    changes = body.model_dump(exclude_unset=True)
    old_status = rvoe.status
    for k, v in changes.items():
        setattr(rvoe, k, v)
    session.add(rvoe)
    if "status" in changes and changes["status"] != old_status:
        audit.record(session, actor=current_user.email, action="rvoe.status_changed",
                     entity="rvoe", entity_id=str(rvoe.id),
                     detail=f"{old_status} -> {rvoe.status}")
    else:
        audit.record(session, actor=current_user.email, action="rvoe.updated",
                     entity="rvoe", entity_id=str(rvoe.id))
    await session.commit()
    await session.refresh(rvoe)
    return rvoe


# --- Plan versions (RT-04) -------------------------------------------------------

@router.get("/plan-versions")
async def list_plan_versions(
    session: SessionDep, _: AnyStaff, rvoe_id: uuid.UUID | None = None
) -> list[PlanVersionPublic]:
    q = select(PlanVersion).order_by(PlanVersion.created_at)
    if rvoe_id:
        q = q.where(PlanVersion.rvoe_id == rvoe_id)
    return (await session.exec(q)).all()


@router.post("/plan-versions", status_code=201)
async def create_plan_version(
    session: SessionDep, current_user: ServiciosEscolares, body: PlanVersionCreate
) -> PlanVersionPublic:
    if await session.get(Rvoe, body.rvoe_id) is None:
        raise HTTPException(status_code=404, detail="RVOE no encontrado")
    plan = PlanVersion(**body.model_dump())
    session.add(plan)
    audit.record(session, actor=current_user.email, action="plan_version.created",
                 entity="plan_version", entity_id=str(plan.id), detail=plan.version_label)
    await session.commit()
    await session.refresh(plan)
    return plan


# --- Plan subjects + seriación (RF-C07) -------------------------------------------

async def _subject_public(session: SessionDep, subject: PlanSubject) -> PlanSubjectPublic:
    prereqs = (
        await session.exec(
            select(SubjectPrerequisite.prerequisite_id).where(
                SubjectPrerequisite.subject_id == subject.id
            )
        )
    ).all()
    return PlanSubjectPublic(**subject.model_dump(), prerequisite_ids=list(prereqs))


@router.get("/plan-versions/{plan_version_id}/subjects")
async def list_plan_subjects(
    session: SessionDep, _: AnyStaff, plan_version_id: uuid.UUID
) -> list[PlanSubjectPublic]:
    subjects = (
        await session.exec(
            select(PlanSubject)
            .where(PlanSubject.plan_version_id == plan_version_id)
            .order_by(PlanSubject.period_number, PlanSubject.code)
        )
    ).all()
    return [await _subject_public(session, s) for s in subjects]


@router.post("/plan-subjects", status_code=201)
async def create_plan_subject(
    session: SessionDep, current_user: ServiciosEscolares, body: PlanSubjectCreate
) -> PlanSubjectPublic:
    if await session.get(PlanVersion, body.plan_version_id) is None:
        raise HTTPException(status_code=404, detail="Plan de estudios no encontrado")
    subject = PlanSubject(**body.model_dump(exclude={"prerequisite_ids"}))
    session.add(subject)
    await session.flush()
    for prereq_id in body.prerequisite_ids:
        prereq = await session.get(PlanSubject, prereq_id)
        if prereq is None or prereq.plan_version_id != body.plan_version_id:
            raise HTTPException(status_code=400, detail="Materia seriada inválida")
        session.add(SubjectPrerequisite(subject_id=subject.id, prerequisite_id=prereq_id))
    audit.record(session, actor=current_user.email, action="plan_subject.created",
                 entity="plan_subject", entity_id=str(subject.id), detail=subject.name)
    await session.commit()
    await session.refresh(subject)
    return await _subject_public(session, subject)


@router.put("/plan-subjects/{subject_id}/prerequisites")
async def set_prerequisites(
    session: SessionDep,
    current_user: ServiciosEscolares,
    subject_id: uuid.UUID,
    prerequisite_ids: list[uuid.UUID],
) -> PlanSubjectPublic:
    subject = await session.get(PlanSubject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    if subject_id in prerequisite_ids:
        raise HTTPException(status_code=400, detail="Una materia no puede seriarse consigo misma")
    existing = (
        await session.exec(
            select(SubjectPrerequisite).where(SubjectPrerequisite.subject_id == subject_id)
        )
    ).all()
    for link in existing:
        await session.delete(link)
    for prereq_id in prerequisite_ids:
        prereq = await session.get(PlanSubject, prereq_id)
        if prereq is None or prereq.plan_version_id != subject.plan_version_id:
            raise HTTPException(status_code=400, detail="Materia seriada inválida")
        session.add(SubjectPrerequisite(subject_id=subject_id, prerequisite_id=prereq_id))
    audit.record(session, actor=current_user.email, action="plan_subject.prerequisites_set",
                 entity="plan_subject", entity_id=str(subject_id))
    await session.commit()
    return await _subject_public(session, subject)


# --- Evaluation scheme (RF-C02) -----------------------------------------------------

@router.get("/plan-subjects/{subject_id}/evaluation-components")
async def list_evaluation_components(
    session: SessionDep, _: AnyStaff, subject_id: uuid.UUID
) -> list[EvaluationComponentPublic]:
    return (
        await session.exec(
            select(EvaluationComponent)
            .where(EvaluationComponent.plan_subject_id == subject_id)
            .order_by(EvaluationComponent.sequence)
        )
    ).all()


@router.post("/evaluation-components", status_code=201)
async def create_evaluation_component(
    session: SessionDep, current_user: ServiciosEscolares, body: EvaluationComponentCreate
) -> EvaluationComponentPublic:
    if await session.get(PlanSubject, body.plan_subject_id) is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    if body.counts_towards_final:
        existing = (
            await session.exec(
                select(EvaluationComponent).where(
                    EvaluationComponent.plan_subject_id == body.plan_subject_id,
                    EvaluationComponent.counts_towards_final == True,  # noqa: E712
                )
            )
        ).all()
        if sum(c.weight_pct for c in existing) + body.weight_pct > 100.001:
            raise HTTPException(
                status_code=400, detail="La ponderación total excedería el 100%"
            )
    component = EvaluationComponent(**body.model_dump())
    session.add(component)
    audit.record(session, actor=current_user.email, action="evaluation_component.created",
                 entity="evaluation_component", entity_id=str(component.id), detail=component.label)
    await session.commit()
    await session.refresh(component)
    return component


@router.delete("/evaluation-components/{component_id}")
async def delete_evaluation_component(
    session: SessionDep, current_user: ServiciosEscolares, component_id: uuid.UUID
) -> dict:
    component = await session.get(EvaluationComponent, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Componente no encontrado")
    await session.delete(component)
    audit.record(session, actor=current_user.email, action="evaluation_component.deleted",
                 entity="evaluation_component", entity_id=str(component_id))
    await session.commit()
    return {"ok": True}


# --- Terms (RT-06) ------------------------------------------------------------------

@router.get("/terms")
async def list_terms(session: SessionDep, _: AnyStaff) -> list[TermPublic]:
    return (await session.exec(select(Term).order_by(Term.start_date.desc()))).all()


@router.post("/terms", status_code=201)
async def create_term(
    session: SessionDep, current_user: ServiciosEscolares, body: TermCreate
) -> TermPublic:
    institution = await get_default_institution(session)
    term = Term(**body.model_dump(), institution_id=institution.id)
    session.add(term)
    audit.record(session, actor=current_user.email, action="term.created",
                 entity="term", entity_id=str(term.id), detail=term.name)
    await session.commit()
    await session.refresh(term)
    return term


def _cal_date(value: object) -> date:
    """Parse a date from the external calendar; a malformed value is the
    calendar's fault, so surface a controlled 422 instead of a 500."""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="El ciclo del calendario tiene fechas inválidas")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="El ciclo del calendario tiene fechas inválidas"
        ) from exc


@router.post("/terms/import", status_code=201)
async def import_term_from_calendar(
    session: SessionDep, current_user: ServiciosEscolares, body: TermImport
) -> TermPublic:
    """Create a scholar term from a calendar term — name + dates come from the
    calendar (the source of truth for periods), no manual date entry."""
    institution = await get_default_institution(session)
    existing = (
        await session.exec(
            select(Term).where(
                Term.institution_id == institution.id,
                Term.calendar_term_id == body.calendar_term_id,
            )
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ese ciclo del calendario ya fue importado")
    cal_terms = await calendar.get_terms()
    cal = next((t for t in cal_terms if str(t.get("id")) == str(body.calendar_term_id)), None)
    if cal is None:
        raise HTTPException(status_code=404, detail="Ciclo del calendario no encontrado")
    if not cal.get("start_date") or not cal.get("end_date"):
        raise HTTPException(
            status_code=422, detail="El ciclo del calendario no tiene fechas definidas"
        )
    term = Term(
        name=str(cal.get("name") or cal.get("code"))[:64],
        start_date=_cal_date(cal["start_date"]),
        end_date=_cal_date(cal["end_date"]),
        institution_id=institution.id,
        calendar_term_id=body.calendar_term_id,
    )
    session.add(term)
    audit.record(session, actor=current_user.email, action="term.imported",
                 entity="term", entity_id=str(term.id), detail=f"{term.name} (calendario)")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # distinguish the calendar-link race from a name clash by the exact
        # constraint name (Postgres names it in the message)
        if "uq_term_calendar" in str(exc.orig).lower():
            raise HTTPException(
                status_code=409, detail="Ese ciclo del calendario ya fue importado"
            ) from exc
        raise HTTPException(
            status_code=409, detail="Ya existe un ciclo con ese nombre"
        ) from exc
    await session.refresh(term)
    return term


@router.post("/terms/{term_id}/sync-calendar")
async def sync_term_from_calendar(
    session: SessionDep, current_user: ServiciosEscolares, term_id: uuid.UUID
) -> TermPublic:
    """Re-pull a linked term's dates from the calendar (if the calendar changed
    them). Colegiatura due dates are derived from these, so they stay in sync."""
    term = await session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    if term.calendar_term_id is None:
        raise HTTPException(status_code=409, detail="El ciclo no está vinculado al calendario")
    cal_terms = await calendar.get_terms()
    cal = next((t for t in cal_terms if str(t.get("id")) == str(term.calendar_term_id)), None)
    if cal is None:
        raise HTTPException(status_code=404, detail="Ciclo del calendario no encontrado")
    if not cal.get("start_date") or not cal.get("end_date"):
        raise HTTPException(
            status_code=422, detail="El ciclo del calendario no tiene fechas definidas"
        )
    term.start_date = _cal_date(cal["start_date"])
    term.end_date = _cal_date(cal["end_date"])
    session.add(term)
    audit.record(session, actor=current_user.email, action="term.synced",
                 entity="term", entity_id=str(term.id), detail="fechas del calendario")
    await session.commit()
    await session.refresh(term)
    return term


@router.patch("/terms/{term_id}")
async def update_term(
    session: SessionDep, current_user: ServiciosEscolares, term_id: uuid.UUID, body: TermUpdate
) -> TermPublic:
    term = await session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(term, k, v)
    session.add(term)
    detail = "captura de calificaciones " + (
        "abierta" if changes.get("grade_capture_open") else "cerrada"
    ) if "grade_capture_open" in changes else None
    audit.record(session, actor=current_user.email, action="term.updated",
                 entity="term", entity_id=str(term_id), detail=detail)
    await session.commit()
    await session.refresh(term)
    return term


# --- Groups (RT-03) ------------------------------------------------------------------

@router.get("/groups")
async def list_groups(
    session: SessionDep,
    _: AnyStaff,
    term_id: uuid.UUID | None = None,
    plan_version_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
) -> list[GroupPublic]:
    q = select(Group).order_by(Group.code)
    if term_id:
        q = q.where(Group.term_id == term_id)
    if plan_version_id:
        q = q.where(Group.plan_version_id == plan_version_id)
    if campus_id:
        q = q.where(Group.campus_id == campus_id)
    return (await session.exec(q)).all()


@router.get("/groups/{group_id}")
async def get_group(session: SessionDep, _: AnyStaff, group_id: uuid.UUID) -> GroupPublic:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return group


async def _validate_promotion_source(
    session: SessionDep, source_id: uuid.UUID, *,
    plan_version_id: uuid.UUID, campus_id: uuid.UUID, period_number: int,
) -> None:
    """A promotion source must be the same plan + plantel and an EARLIER period —
    not an arbitrary/future/unrelated group."""
    source = await session.get(Group, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Grupo de origen no encontrado")
    if (
        source.plan_version_id != plan_version_id
        or source.campus_id != campus_id
        or source.period_number >= period_number
    ):
        raise HTTPException(
            status_code=422,
            detail="El grupo de origen debe ser del mismo plan y plantel, de un periodo anterior",
        )


@router.post("/groups", status_code=201)
async def create_group(
    session: SessionDep, current_user: AcademicStaff, body: GroupCreate
) -> GroupPublic:
    rvoe = await require_operable_rvoe(session, body.plan_version_id)  # RT-03
    if await session.get(Term, body.term_id) is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    if body.promotes_from_group_id is not None:
        await _validate_promotion_source(
            session, body.promotes_from_group_id,
            plan_version_id=body.plan_version_id, campus_id=rvoe.campus_id,
            period_number=body.period_number,
        )
    # campus is derived from the plan's RVOE, not supplied by the client
    group = Group(**body.model_dump(), campus_id=rvoe.campus_id)
    session.add(group)
    await session.flush()
    # seed the group with the plan subjects of its period (teacher unassigned);
    # saves adding each materia by hand — remove any that don't apply.
    period_subjects = (
        await session.exec(
            select(PlanSubject).where(
                PlanSubject.plan_version_id == group.plan_version_id,
                PlanSubject.period_number == group.period_number,
            )
        )
    ).all()
    for ps in period_subjects:
        session.add(GroupSubject(group_id=group.id, plan_subject_id=ps.id))
    audit.record(session, actor=current_user.email, action="group.created",
                 entity="group", entity_id=str(group.id),
                 detail=f"{group.code} · {len(period_subjects)} materias")
    await session.commit()
    await session.refresh(group)
    return group


@router.patch("/groups/{group_id}")
async def update_group(
    session: SessionDep, current_user: AcademicStaff, group_id: uuid.UUID, body: GroupUpdate
) -> GroupPublic:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("promotes_from_group_id") is not None:
        await _validate_promotion_source(
            session, changes["promotes_from_group_id"],
            plan_version_id=group.plan_version_id, campus_id=group.campus_id,
            period_number=group.period_number,
        )
    for k, v in changes.items():
        setattr(group, k, v)
    session.add(group)
    audit.record(session, actor=current_user.email, action="group.updated",
                 entity="group", entity_id=str(group_id))
    await session.commit()
    await session.refresh(group)
    return group


@router.get("/groups/{group_id}/students")
async def list_group_students(
    session: SessionDep, _: AnyStaff, group_id: uuid.UUID
) -> list[dict]:
    """Enrolled students of a group (staff view; the integration API has its own)."""
    from app.models import GroupEnrollment, Student

    rows = (
        await session.exec(
            select(Student, GroupEnrollment)
            .join(GroupEnrollment, GroupEnrollment.student_id == Student.id)
            .where(GroupEnrollment.group_id == group_id)
            .order_by(Student.full_name)
        )
    ).all()
    return [
        {
            "student_id": str(s.id),
            "full_name": s.full_name,
            "curp": s.curp,
            "enrollment_number": s.enrollment_number,
            "kind": e.kind,
            "status": e.status,
        }
        for s, e in rows
    ]


@router.get("/groups/{group_id}/subjects")
async def list_group_subjects(
    session: SessionDep, _: AnyStaff, group_id: uuid.UUID
) -> list[GroupSubjectPublic]:
    return (
        await session.exec(select(GroupSubject).where(GroupSubject.group_id == group_id))
    ).all()


@router.post("/group-subjects", status_code=201)
async def create_group_subject(
    session: SessionDep, current_user: AcademicStaff, body: GroupSubjectCreate
) -> GroupSubjectPublic:
    group = await session.get(Group, body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    subject = await session.get(PlanSubject, body.plan_subject_id)
    if subject is None or subject.plan_version_id != group.plan_version_id:
        raise HTTPException(status_code=400, detail="La materia no pertenece al plan del grupo")
    # upsert: groups are seeded with their period's subjects on creation, so
    # "add materia" (e.g. to assign a teacher) updates the existing row.
    group_subject = (
        await session.exec(
            select(GroupSubject).where(
                GroupSubject.group_id == body.group_id,
                GroupSubject.plan_subject_id == body.plan_subject_id,
            )
        )
    ).first()
    if group_subject:
        group_subject.teacher_user_id = body.teacher_user_id
        group_subject.schedule_text = body.schedule_text
    else:
        group_subject = GroupSubject(**body.model_dump())
    session.add(group_subject)
    audit.record(session, actor=current_user.email, action="group_subject.created",
                 entity="group_subject", entity_id=str(group_subject.id))
    await session.commit()
    await session.refresh(group_subject)
    return group_subject


@router.patch("/group-subjects/{group_subject_id}")
async def update_group_subject(
    session: SessionDep,
    current_user: AcademicStaff,
    group_subject_id: uuid.UUID,
    body: GroupSubjectCreate,
) -> GroupSubjectPublic:
    group_subject = await session.get(GroupSubject, group_subject_id)
    if group_subject is None:
        raise HTTPException(status_code=404, detail="Materia de grupo no encontrada")
    if body.plan_subject_id != group_subject.plan_subject_id:
        group = await session.get(Group, group_subject.group_id)
        subject = await session.get(PlanSubject, body.plan_subject_id)
        if subject is None or group is None or subject.plan_version_id != group.plan_version_id:
            raise HTTPException(status_code=400, detail="La materia no pertenece al plan del grupo")
        group_subject.plan_subject_id = body.plan_subject_id
    group_subject.teacher_user_id = body.teacher_user_id
    group_subject.schedule_text = body.schedule_text
    session.add(group_subject)
    audit.record(session, actor=current_user.email, action="group_subject.updated",
                 entity="group_subject", entity_id=str(group_subject_id))
    await session.commit()
    await session.refresh(group_subject)
    return group_subject
