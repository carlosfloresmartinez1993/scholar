"""Catalog routes: institution, campuses, programs, RVOE, plan versions,
subjects (+seriación, evaluation schemes), terms and groups."""
import uuid
from datetime import date

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, or_, select

from app.api.deps import (
    AnyStaff,
    CampusScope,
    CanConfiguracionEdit,
    CanGrupos,
    CanGruposEdit,
    CanPeriodosEdit,
    CanPlantelesEdit,
    CanProgramas,
    CanProgramasEdit,
    CanStudentsRead,
    SessionDep,
    StaffOrTeacher,
    ensure_in_scope,
    is_teacher,
)
from app.models import (
    Campus,
    CampusCreate,
    CampusPublic,
    CampusUpdate,
    CalendarProgramsImport,
    CalendarGroupsImport,
    EducationLevel,
    EducationLevelCreate,
    EducationLevelPublic,
    EducationLevelUpdate,
    PlanVersionUpdate,
    EvaluationComponent,
    EvaluationComponentCreate,
    EvaluationComponentPublic,
    REPLACEMENT_KINDS,
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
    PlanSubjectUpdate,
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
    UserRole,
)
from app.models.common import utcnow
from app.services import audit, calendar
from app.services.files import save_upload
from app.services.calendar_sync import (
    groups_preview,
    import_groups,
    import_programs,
    programs_preview,
    seed_group_subjects,
    sync_campuses,
)
from app.services.levels import levels_of, require_level
from app.services.rvoe_campuses import (
    campus_ids_of,
    campus_map,
    group_campus,
    offered_in,
    set_extra_campuses,
)
from app.services.academics import internal_group_clause, require_operable_rvoe

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
    session: SessionDep, current_user: CanConfiguracionEdit, body: InstitutionUpdate
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
async def list_campuses(session: SessionDep, _: StaffOrTeacher) -> list[CampusPublic]:
    return (await session.exec(select(Campus).order_by(Campus.name))).all()


@router.post("/campuses", status_code=201)
async def create_campus(
    session: SessionDep, current_user: CanPlantelesEdit, body: CampusCreate
) -> CampusPublic:
    institution_id = body.institution_id or (await get_default_institution(session)).id
    campus = Campus(**body.model_dump(exclude={"institution_id"}), institution_id=institution_id)
    session.add(campus)
    audit.record(session, actor=current_user.email, action="campus.created",
                 entity="campus", entity_id=str(campus.id), detail=campus.name)
    await session.commit()
    await session.refresh(campus)
    return campus


LOGO_TYPES = {"image/png", "image/jpeg"}  # what the kárdex PDF can embed
LOGO_MAX_BYTES = 2 * 1024 * 1024


def _remove_file(path: str | None) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass  # a leftover file is harmless


@router.post("/campuses/{campus_id}/logo")
async def upload_campus_logo(
    session: SessionDep, current_user: CanPlantelesEdit, campus_id: uuid.UUID, file: UploadFile
) -> CampusPublic:
    """The logo that goes on top of the kárdex of this campus' students."""
    campus = await session.get(Campus, campus_id)
    if campus is None:
        raise HTTPException(status_code=404, detail="Campus no encontrado")
    path = await save_upload(
        file, "campus-logos", allowed_types=LOGO_TYPES, max_bytes=LOGO_MAX_BYTES,
        type_error_detail="El logo debe ser PNG o JPG",
    )
    old = campus.logo_path
    campus.logo_path, campus.logo_content_type = path, file.content_type
    campus.logo_updated_at = utcnow()
    session.add(campus)
    audit.record(session, actor=current_user.email, action="campus.logo_uploaded",
                 entity="campus", entity_id=str(campus_id), detail=campus.name)
    await session.commit()
    await session.refresh(campus)
    _remove_file(old)
    return campus


@router.get("/campuses/{campus_id}/logo")
async def get_campus_logo(session: SessionDep, _: AnyStaff, campus_id: uuid.UUID) -> FileResponse:
    campus = await session.get(Campus, campus_id)
    if campus is None or not campus.logo_path or not Path(campus.logo_path).is_file():
        raise HTTPException(status_code=404, detail="Este plantel no tiene logo")
    return FileResponse(campus.logo_path, media_type=campus.logo_content_type or "image/png")


@router.delete("/campuses/{campus_id}/logo")
async def delete_campus_logo(
    session: SessionDep, current_user: CanPlantelesEdit, campus_id: uuid.UUID
) -> CampusPublic:
    campus = await session.get(Campus, campus_id)
    if campus is None:
        raise HTTPException(status_code=404, detail="Campus no encontrado")
    old = campus.logo_path
    campus.logo_path = campus.logo_content_type = campus.logo_updated_at = None
    session.add(campus)
    audit.record(session, actor=current_user.email, action="campus.logo_removed",
                 entity="campus", entity_id=str(campus_id), detail=campus.name)
    await session.commit()
    await session.refresh(campus)
    _remove_file(old)
    return campus


@router.patch("/campuses/{campus_id}")
async def update_campus(
    session: SessionDep, current_user: CanPlantelesEdit, campus_id: uuid.UUID,
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
    if data.get("name") is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=422, detail="El nombre no puede quedar vacío")
    for k, v in data.items():
        if v is None and k != "calendar_campus_id":
            continue  # only the calendar link can be cleared
        setattr(campus, k, v)
    session.add(campus)
    audit.record(session, actor=current_user.email, action="campus.updated",
                 entity="campus", entity_id=str(campus_id))
    await session.commit()
    await session.refresh(campus)
    return campus


# --- Niveles educativos -----------------------------------------------------------

@router.get("/education-levels")
async def list_education_levels(
    session: SessionDep, _: AnyStaff, include_inactive: bool = False
) -> list[EducationLevelPublic]:
    institution = await get_default_institution(session)
    return await levels_of(session, institution.id, active_only=not include_inactive)


@router.post("/education-levels", status_code=201)
async def create_education_level(
    session: SessionDep, current_user: CanProgramasEdit, body: EducationLevelCreate
) -> EducationLevelPublic:
    institution = await get_default_institution(session)
    code = body.code.strip().lower().replace(" ", "_")
    exists = (
        await session.exec(
            select(EducationLevel).where(
                EducationLevel.institution_id == institution.id, EducationLevel.code == code
            )
        )
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Ya existe un nivel con esa clave")
    level = EducationLevel(institution_id=institution.id, code=code, name=body.name.strip(),
                           sort_order=body.sort_order)
    session.add(level)
    audit.record(session, actor=current_user.email, action="education_level.created",
                 entity="education_level", entity_id=str(level.id), detail=level.name)
    await session.commit()
    await session.refresh(level)
    return level


@router.patch("/education-levels/{level_id}")
async def update_education_level(
    session: SessionDep, current_user: CanProgramasEdit, level_id: uuid.UUID,
    body: EducationLevelUpdate,
) -> EducationLevelPublic:
    level = await session.get(EducationLevel, level_id)
    if level is None:
        raise HTTPException(status_code=404, detail="Nivel no encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(level, k, v.strip() if isinstance(v, str) else v)
    session.add(level)
    audit.record(session, actor=current_user.email, action="education_level.updated",
                 entity="education_level", entity_id=str(level.id), detail=level.name)
    await session.commit()
    await session.refresh(level)
    return level


@router.delete("/education-levels/{level_id}", status_code=204)
async def delete_education_level(
    session: SessionDep, current_user: CanProgramasEdit, level_id: uuid.UUID
) -> None:
    level = await session.get(EducationLevel, level_id)
    if level is None:
        raise HTTPException(status_code=404, detail="Nivel no encontrado")
    used = (
        await session.exec(
            select(Program.id).where(
                Program.institution_id == level.institution_id, Program.level == level.code
            )
        )
    ).first()
    if used:
        raise HTTPException(status_code=409, detail="Hay carreras con ese nivel: desactívalo en lugar de borrarlo")
    await session.delete(level)
    audit.record(session, actor=current_user.email, action="education_level.deleted",
                 entity="education_level", entity_id=str(level_id), detail=level.name)
    await session.commit()


# --- Programs ------------------------------------------------------------------

@router.get("/programs")
async def list_programs(
    session: SessionDep, _: AnyStaff, scope: CampusScope
) -> list[ProgramPublic]:
    q = select(Program).order_by(Program.name)
    # Programs carry campus only via their RVOEs: with a campus chosen, a program
    # shows when it has an RVOE there — or none yet (just created or imported: it
    # has to be visible to capture its first RVOE).
    if scope is not None:
        q = q.where(
            or_(
                Program.id.in_(  # type: ignore[attr-defined]
                    select(Rvoe.program_id).where(offered_in(scope))
                ),
                ~Program.id.in_(select(Rvoe.program_id)),  # type: ignore[attr-defined]
            )
        )
    programs = (await session.exec(q)).all()
    rvoes = (await session.exec(select(Rvoe).order_by(Rvoe.created_at))).all()
    campuses = await campus_map(session, rvoes)
    by_program: dict = {}
    for rvoe in rvoes:
        by_program.setdefault(rvoe.program_id, []).append(
            {"id": rvoe.id, "agreement_number": rvoe.agreement_number, "campus_ids": campuses[rvoe.id]}
        )
    return [ProgramPublic(**p.model_dump(), rvoes=by_program.get(p.id, [])) for p in programs]


@router.post("/programs", status_code=201)
async def create_program(
    session: SessionDep, current_user: CanProgramasEdit, body: ProgramCreate
) -> ProgramPublic:
    institution = await get_default_institution(session)
    await require_level(session, institution.id, body.level)
    code = body.code.strip()
    if (await session.exec(
        select(Program.id).where(Program.institution_id == institution.id, Program.code == code)
    )).first():
        raise HTTPException(status_code=409, detail="Ya existe una carrera con esa clave")
    program = Program(**body.model_dump(exclude={"code"}), code=code, institution_id=institution.id)
    session.add(program)
    audit.record(session, actor=current_user.email, action="program.created",
                 entity="program", entity_id=str(program.id), detail=program.name)
    await session.commit()
    await session.refresh(program)
    return program


@router.patch("/programs/{program_id}")
async def update_program(
    session: SessionDep,
    current_user: CanProgramasEdit,
    program_id: uuid.UUID,
    body: ProgramUpdate,
) -> ProgramPublic:
    program = await session.get(Program, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Programa no encontrado")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("level") is not None and changes["level"] != program.level:
        await require_level(session, program.institution_id, changes["level"])
    if changes.get("code") is not None:
        changes["code"] = changes["code"].strip()
        clash = (
            await session.exec(
                select(Program.id).where(
                    Program.institution_id == program.institution_id,
                    Program.code == changes["code"], Program.id != program.id,
                )
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ya existe una carrera con esa clave")
    if changes.get("name") is not None:
        changes["name"] = changes["name"].strip()
    for k, v in changes.items():
        if v is None and k != "calendar_program_id":
            continue  # only the calendar link can be cleared
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


@router.post("/campuses/sync-calendar")
async def sync_campuses_from_calendar(session: SessionDep, current_user: CanPlantelesEdit) -> dict:
    """Bring the calendar's campuses: create the missing ones, link the matching
    ones; a campus already linked is never overwritten."""
    result = await sync_campuses(session, current_user, await get_default_institution(session))
    await session.commit()
    return result


@router.get("/calendar/programs/preview")
async def calendar_programs_preview(session: SessionDep, _: CanProgramas) -> list[dict]:
    """The calendar's programs and what importing each would do."""
    return await programs_preview(session, await get_default_institution(session))


@router.post("/programs/import-calendar")
async def import_programs_from_calendar(
    session: SessionDep, current_user: CanProgramasEdit, body: CalendarProgramsImport
) -> dict:
    """Copy the chosen calendar programs into scholar (or link the existing ones)."""
    result = await import_programs(
        session, current_user, await get_default_institution(session), body.calendar_program_ids
    )
    await session.commit()
    return result


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
    session: SessionDep, _: AnyStaff, scope: CampusScope, program_id: uuid.UUID | None = None
) -> list[RvoePublic]:
    q = select(Rvoe).order_by(Rvoe.created_at)
    if scope is not None:
        q = q.where(offered_in(scope))
    if program_id:
        q = q.where(Rvoe.program_id == program_id)
    rvoes = (await session.exec(q)).all()
    campuses = await campus_map(session, rvoes)
    return [RvoePublic(**r.model_dump(), campus_ids=campuses[r.id]) for r in rvoes]


@router.post("/rvoes", status_code=201)
async def create_rvoe(
    session: SessionDep, current_user: CanProgramasEdit, scope: CampusScope, body: RvoeCreate
) -> RvoePublic:
    ensure_in_scope(scope, body.campus_id)  # RVOE lives in a specific campus
    if await session.get(Program, body.program_id) is None:
        raise HTTPException(status_code=404, detail="Programa no encontrado")
    if await session.get(Campus, body.campus_id) is None:
        raise HTTPException(status_code=404, detail="Plantel no encontrado")
    dup = (
        await session.exec(select(Rvoe).where(Rvoe.agreement_number == body.agreement_number))
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="Ya existe un RVOE con ese número de acuerdo")
    rvoe = Rvoe(**body.model_dump(exclude={"extra_campus_ids"}))
    session.add(rvoe)
    await session.flush()
    for campus_id in body.extra_campus_ids:
        ensure_in_scope(scope, campus_id)
    await set_extra_campuses(session, rvoe, body.extra_campus_ids)
    audit.record(session, actor=current_user.email, action="rvoe.created",
                 entity="rvoe", entity_id=str(rvoe.id), detail=rvoe.agreement_number)
    await session.commit()
    await session.refresh(rvoe)
    return RvoePublic(**rvoe.model_dump(), campus_ids=await campus_ids_of(session, rvoe))


@router.patch("/rvoes/{rvoe_id}")
async def update_rvoe(
    session: SessionDep, current_user: CanProgramasEdit, rvoe_id: uuid.UUID, body: RvoeUpdate
) -> RvoePublic:
    rvoe = await session.get(Rvoe, rvoe_id)
    if rvoe is None:
        raise HTTPException(status_code=404, detail="RVOE no encontrado")
    changes = body.model_dump(exclude_unset=True)
    extra = changes.pop("extra_campus_ids", None)
    old_status = rvoe.status
    for k, v in changes.items():
        setattr(rvoe, k, v)
    session.add(rvoe)
    if extra is not None:
        await set_extra_campuses(session, rvoe, extra)
    if "status" in changes and changes["status"] != old_status:
        audit.record(session, actor=current_user.email, action="rvoe.status_changed",
                     entity="rvoe", entity_id=str(rvoe.id),
                     detail=f"{old_status} -> {rvoe.status}")
    else:
        audit.record(session, actor=current_user.email, action="rvoe.updated",
                     entity="rvoe", entity_id=str(rvoe.id))
    await session.commit()
    await session.refresh(rvoe)
    return RvoePublic(**rvoe.model_dump(), campus_ids=await campus_ids_of(session, rvoe))


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
    session: SessionDep, current_user: CanProgramasEdit, body: PlanVersionCreate
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


@router.patch("/plan-versions/{plan_version_id}")
async def update_plan_version(
    session: SessionDep, current_user: CanProgramasEdit, plan_version_id: uuid.UUID,
    body: PlanVersionUpdate,
) -> PlanVersionPublic:
    plan = await session.get(PlanVersion, plan_version_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan de estudios no encontrado")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "periods_count" in changes:
        top = (
            await session.exec(
                select(func.max(PlanSubject.period_number)).where(PlanSubject.plan_version_id == plan.id)
            )
        ).one()
        if top and changes["periods_count"] < top:
            raise HTTPException(
                status_code=409, detail=f"El plan tiene materias hasta el periodo {top}"
            )
    if "version_label" in changes:
        changes["version_label"] = changes["version_label"].strip()
        clash = (
            await session.exec(
                select(PlanVersion.id).where(
                    PlanVersion.rvoe_id == plan.rvoe_id,
                    PlanVersion.version_label == changes["version_label"],
                    PlanVersion.id != plan.id,
                )
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ese RVOE ya tiene un plan con esa etiqueta")
    for k, v in changes.items():
        setattr(plan, k, v)
    session.add(plan)
    audit.record(session, actor=current_user.email, action="plan_version.updated",
                 entity="plan_version", entity_id=str(plan.id))
    await session.commit()
    await session.refresh(plan)
    return plan


@router.get("/plan-versions/{plan_version_id}/subjects")
async def list_plan_subjects(
    session: SessionDep, _: StaffOrTeacher, plan_version_id: uuid.UUID
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
    session: SessionDep, current_user: CanProgramasEdit, body: PlanSubjectCreate
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


@router.patch("/plan-subjects/{subject_id}")
async def update_plan_subject(
    session: SessionDep, current_user: CanProgramasEdit, subject_id: uuid.UUID,
    body: PlanSubjectUpdate,
) -> PlanSubjectPublic:
    """Edit a materia of the plan (name, clave, cuatrimestre, créditos, horas). The
    history keeps pointing at it, so kárdex and actas show the new values."""
    subject = await session.get(PlanSubject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "code" in changes:
        changes["code"] = changes["code"].strip()
        clash = (
            await session.exec(
                select(PlanSubject).where(
                    PlanSubject.plan_version_id == subject.plan_version_id,
                    PlanSubject.code == changes["code"],
                    PlanSubject.id != subject_id,
                )
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ya existe una materia con esa clave en el plan")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío")
    before = f"{subject.code} — {subject.name}"
    for field, value in changes.items():
        setattr(subject, field, value)
    session.add(subject)
    audit.record(session, actor=current_user.email, action="plan_subject.updated",
                 entity="plan_subject", entity_id=str(subject_id),
                 detail=f"{before} -> {subject.code} — {subject.name}")
    await session.commit()
    await session.refresh(subject)
    return await _subject_public(session, subject)


@router.put("/plan-subjects/{subject_id}/prerequisites")
async def set_prerequisites(
    session: SessionDep,
    current_user: CanProgramasEdit,
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
    session: SessionDep, current_user: CanProgramasEdit, body: EvaluationComponentCreate
) -> EvaluationComponentPublic:
    if await session.get(PlanSubject, body.plan_subject_id) is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    if body.kind in REPLACEMENT_KINDS:
        # extraordinario / título de suficiencia replace the final, never weigh in it
        body.counts_towards_final = False
        body.weight_pct = 0
    if body.counts_towards_final:
        existing = (
            await session.exec(
                select(EvaluationComponent).where(
                    EvaluationComponent.plan_subject_id == body.plan_subject_id,
                )
            )
        ).all()
        if sum(c.weight_pct for c in existing if c.weighs_in_final) + body.weight_pct > 100.001:
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
    session: SessionDep, current_user: CanProgramasEdit, component_id: uuid.UUID
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
async def list_terms(session: SessionDep, _: StaffOrTeacher) -> list[TermPublic]:
    return (await session.exec(select(Term).order_by(Term.start_date.desc()))).all()


@router.post("/terms", status_code=201)
async def create_term(
    session: SessionDep, current_user: CanPeriodosEdit, body: TermCreate
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
    session: SessionDep, current_user: CanPeriodosEdit, body: TermImport
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
    session: SessionDep, current_user: CanPeriodosEdit, term_id: uuid.UUID
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
    session: SessionDep, current_user: CanPeriodosEdit, term_id: uuid.UUID, body: TermUpdate
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
    current_user: StaffOrTeacher,
    scope: CampusScope,
    term_id: uuid.UUID | None = None,
    plan_version_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
    include_internal: bool = False,
) -> list[GroupPublic]:
    q = select(Group).order_by(Group.code)
    if not include_internal:  # equivalencia/convalidación groups: nobody attends them
        q = q.where(~internal_group_clause())
    teacher = is_teacher(current_user)  # a role limited to its own materias
    if teacher:
        # a profesor may teach in any plantel: they see the groups where they have a
        # materia assigned, wherever it is (not the planteles of their account)
        q = q.where(Group.id.in_(  # type: ignore[attr-defined]
            select(GroupSubject.group_id).where(GroupSubject.teacher_user_id == current_user.id)
        ))
    elif scope is not None:
        q = q.where(Group.campus_id.in_(scope))  # type: ignore[attr-defined]
    if term_id:
        q = q.where(Group.term_id == term_id)
    if plan_version_id:
        q = q.where(Group.plan_version_id == plan_version_id)
    if campus_id:
        if not teacher:
            ensure_in_scope(scope, campus_id)  # a ?campus_id outside membership is 403
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
    session: SessionDep, current_user: CanGruposEdit, scope: CampusScope, body: GroupCreate
) -> GroupPublic:
    rvoe = await require_operable_rvoe(session, body.plan_version_id)  # RT-03
    # campus is derived from the plan's RVOE — enforce it is one you belong to
    campus_id = await group_campus(session, rvoe, body.campus_id)
    ensure_in_scope(scope, campus_id)
    if await session.get(Term, body.term_id) is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    if body.promotes_from_group_id is not None:
        await _validate_promotion_source(
            session, body.promotes_from_group_id,
            plan_version_id=body.plan_version_id, campus_id=campus_id,
            period_number=body.period_number,
        )
    # a plantel where the plan's RVOE is offered (its main one by default)
    group = Group(**body.model_dump(exclude={"campus_id"}), campus_id=campus_id)
    session.add(group)
    await session.flush()
    seeded = await seed_group_subjects(session, group)
    audit.record(session, actor=current_user.email, action="group.created",
                 entity="group", entity_id=str(group.id),
                 detail=f"{group.code} · {seeded} materias")
    await session.commit()
    await session.refresh(group)
    return group


@router.patch("/groups/{group_id}")
async def update_group(
    session: SessionDep, current_user: CanGruposEdit, group_id: uuid.UUID, body: GroupUpdate
) -> GroupPublic:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    changes = body.model_dump(exclude_unset=True)
    for key in ("code", "period_number", "is_active"):
        if key in changes and changes[key] is None:
            del changes[key]
    if "code" in changes:
        changes["code"] = changes["code"].strip()
        clash = (
            await session.exec(
                select(Group.id).where(
                    Group.term_id == group.term_id, Group.campus_id == group.campus_id,
                    Group.code == changes["code"], Group.id != group.id,
                )
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ya hay un grupo con esa clave en el ciclo y plantel")
    reseed = False
    if "period_number" in changes and changes["period_number"] != group.period_number:
        if await _group_in_use(session, group):
            raise HTTPException(
                status_code=409,
                detail="El grupo ya tiene alumnos o clases: su cuatrimestre no se puede cambiar",
            )
        plan = await session.get(PlanVersion, group.plan_version_id)
        if plan and changes["period_number"] > plan.periods_count:
            raise HTTPException(status_code=422, detail=f"El plan tiene {plan.periods_count} periodos")
        reseed = True
    if changes.get("promotes_from_group_id") is not None:
        await _validate_promotion_source(
            session, changes["promotes_from_group_id"],
            plan_version_id=group.plan_version_id, campus_id=group.campus_id,
            period_number=changes.get("period_number", group.period_number),
        )
    for k, v in changes.items():
        setattr(group, k, v)
    session.add(group)
    if reseed:  # the materias of the new cuatrimestre
        for gs in (await session.exec(select(GroupSubject).where(GroupSubject.group_id == group.id))).all():
            await session.delete(gs)
        await session.flush()
        await seed_group_subjects(session, group)
    audit.record(session, actor=current_user.email, action="group.updated",
                 entity="group", entity_id=str(group_id))
    await session.commit()
    await session.refresh(group)
    return group


async def _group_in_use(session: SessionDep, group: Group) -> bool:
    """Students enrolled (in any status), class sessions or actas."""
    from app.models import ClassSession, GradeActa, GroupEnrollment

    if (await session.exec(select(GroupEnrollment.id).where(GroupEnrollment.group_id == group.id))).first():
        return True
    subjects = select(GroupSubject.id).where(GroupSubject.group_id == group.id)
    if (await session.exec(select(ClassSession.id).where(ClassSession.group_subject_id.in_(subjects)))).first():  # type: ignore[attr-defined]
        return True
    return (await session.exec(select(GradeActa.id).where(GradeActa.group_subject_id.in_(subjects)))).first() is not None  # type: ignore[attr-defined]


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    session: SessionDep, current_user: CanGruposEdit, scope: CampusScope, group_id: uuid.UUID
) -> None:
    """Borrar un grupo creado por error. Con alumnos, clases o actas no se puede:
    se desactiva."""
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    ensure_in_scope(scope, group.campus_id)
    if await _group_in_use(session, group):
        raise HTTPException(
            status_code=409, detail="El grupo tiene alumnos, clases o actas: desactívalo en lugar de borrarlo"
        )
    for later in (await session.exec(select(Group).where(Group.promotes_from_group_id == group.id))).all():
        later.promotes_from_group_id = None
        session.add(later)
    for gs in (await session.exec(select(GroupSubject).where(GroupSubject.group_id == group.id))).all():
        await session.delete(gs)
    await session.flush()
    await session.delete(group)
    audit.record(session, actor=current_user.email, action="group.deleted",
                 entity="group", entity_id=str(group_id), detail=group.code)
    await session.commit()


@router.get("/terms/{term_id}/calendar-groups/preview")
async def calendar_groups_preview(
    session: SessionDep, _: CanGrupos, term_id: uuid.UUID
) -> dict:
    """The calendar's groups of this term and what importing each would do."""
    term = await session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    return await groups_preview(session, term)


@router.post("/terms/{term_id}/calendar-groups/import")
async def import_calendar_groups(
    session: SessionDep, current_user: CanGruposEdit, scope: CampusScope, term_id: uuid.UUID,
    body: CalendarGroupsImport,
) -> dict:
    """Create the chosen calendar groups in this term (plan and cuatrimestre as
    confirmed in the preview); each stays editable and deletable here."""
    term = await session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Ciclo no encontrado")
    result = await import_groups(session, current_user, term, [i.model_dump() for i in body.items], scope)
    await session.commit()
    return result


@router.get("/groups/{group_id}/students")
async def list_group_students(
    session: SessionDep, _: CanStudentsRead, group_id: uuid.UUID
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
            "subjects_only": e.subjects_only,
        }
        for s, e in rows
    ]


@router.get("/groups/{group_id}/subjects")
async def list_group_subjects(
    session: SessionDep, current_user: StaffOrTeacher, group_id: uuid.UUID
) -> list[GroupSubjectPublic]:
    q = select(GroupSubject).where(GroupSubject.group_id == group_id)
    if is_teacher(current_user):
        q = q.where(GroupSubject.teacher_user_id == current_user.id)  # only their materias
    return (await session.exec(q)).all()


@router.post("/group-subjects", status_code=201)
async def create_group_subject(
    session: SessionDep, current_user: CanGruposEdit, body: GroupSubjectCreate
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
    current_user: CanGruposEdit,
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
