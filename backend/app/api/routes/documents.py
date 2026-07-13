"""Documentation / expediente: intake checklist (RF-D02), upload & review
(RF-D03), official documents with folio (RF-D04/D05), regulations (RF-D06),
teacher expedientes (RF-D07) and the consolidated expediente view (RF-D01)."""
import json
import uuid

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import select

from app.api.deps import AnyStaff, ServiciosEscolares, SessionDep
from app.api.routes.catalog import get_default_institution
from app.models import (
    DocumentRequirement,
    DocumentReviewIn,
    Group,
    GroupEnrollment,
    IssueDocumentIn,
    IssuedDocument,
    IssuedDocumentKind,
    IssuedDocumentPublic,
    PlanVersion,
    Program,
    Regulation,
    RegulationAcceptance,
    RegulationCreate,
    RegulationPublic,
    RequirementCreate,
    RequirementPublic,
    ReviewStatus,
    Rvoe,
    Student,
    StudentDocument,
    StudentDocumentPublic,
    TeacherDocument,
    TeacherDocumentPublic,
    TeacherProfile,
    TeacherProfilePublic,
    TeacherProfileUpsert,
    User,
    UserRole,
)
from app.models.common import utcnow
from app.services import audit
from app.services.academics import curricular_progress, kardex_rows, require_operable_rvoe
from app.services.files import save_upload
from app.services.folios import next_folio
from app.services.treasury import has_blocking_debt, overdue_balance

router = APIRouter(prefix="/documents", tags=["documents"])


# --- Requirements checklist (RF-D02) --------------------------------------------

@router.get("/requirements")
async def list_requirements(session: SessionDep, _: AnyStaff) -> list[RequirementPublic]:
    return (
        await session.exec(
            select(DocumentRequirement).where(DocumentRequirement.is_active == True)  # noqa: E712
        )
    ).all()


@router.post("/requirements", status_code=201)
async def create_requirement(
    session: SessionDep, current_user: ServiciosEscolares, body: RequirementCreate
) -> RequirementPublic:
    institution = await get_default_institution(session)
    requirement = DocumentRequirement(**body.model_dump(), institution_id=institution.id)
    session.add(requirement)
    audit.record(session, actor=current_user.email, action="doc_requirement.created",
                 entity="doc_requirement", entity_id=str(requirement.id), detail=requirement.name)
    await session.commit()
    await session.refresh(requirement)
    return requirement


# --- Student documents (RF-D03) ---------------------------------------------------

@router.post("/students/{student_id}/documents", status_code=201)
async def upload_student_document(
    session: SessionDep,
    current_user: ServiciosEscolares,
    student_id: uuid.UUID,
    file: UploadFile,
    title: str,
    requirement_id: uuid.UUID | None = None,
) -> StudentDocumentPublic:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    previous = (
        await session.exec(
            select(StudentDocument)
            .where(StudentDocument.student_id == student_id, StudentDocument.title == title)
            .order_by(StudentDocument.version.desc())
        )
    ).first()
    path = await save_upload(file, f"students/{student_id}")
    document = StudentDocument(
        student_id=student_id,
        requirement_id=requirement_id,
        title=title,
        file_path=path,
        filename=file.filename or "documento",
        content_type=file.content_type or "application/octet-stream",
        version=(previous.version + 1) if previous else 1,
        uploaded_by=current_user.id,
    )
    session.add(document)
    audit.record(session, actor=current_user.email, action="student_document.uploaded",
                 entity="student_document", entity_id=str(document.id),
                 detail=f"{title} v{document.version}")
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/students/{student_id}/documents")
async def list_student_documents(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID
) -> list[StudentDocumentPublic]:
    return (
        await session.exec(
            select(StudentDocument)
            .where(StudentDocument.student_id == student_id)
            .order_by(StudentDocument.uploaded_at.desc())
        )
    ).all()


@router.get("/files/{document_id}")
async def download_student_document(
    session: SessionDep, _: AnyStaff, document_id: uuid.UUID
) -> FileResponse:
    document = await session.get(StudentDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return FileResponse(
        document.file_path, media_type=document.content_type, filename=document.filename
    )


@router.post("/student-documents/{document_id}/review")
async def review_student_document(
    session: SessionDep,
    current_user: ServiciosEscolares,
    document_id: uuid.UUID,
    body: DocumentReviewIn,
) -> StudentDocumentPublic:
    document = await session.get(StudentDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    old_status = document.status
    document.status = body.status
    document.reject_reason = body.reject_reason if body.status == ReviewStatus.rechazado else ""
    document.reviewed_by = current_user.id
    document.reviewed_at = utcnow()
    session.add(document)
    audit.record(session, actor=current_user.email, action="student_document.reviewed",
                 entity="student_document", entity_id=str(document_id),
                 detail=f"{old_status} -> {body.status}")
    await session.commit()
    await session.refresh(document)
    return document


# --- Expediente view (RF-D01/D02) ----------------------------------------------------

@router.get("/students/{student_id}/expediente")
async def expediente(session: SessionDep, _: AnyStaff, student_id: uuid.UUID) -> dict:
    """Single view: data, checklist status, documents, issued docs, debt flag."""
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    requirements = (
        await session.exec(
            select(DocumentRequirement).where(
                DocumentRequirement.is_active == True,  # noqa: E712
            )
        )
    ).all()
    documents = (
        await session.exec(
            select(StudentDocument).where(StudentDocument.student_id == student_id)
        )
    ).all()
    accepted_by_requirement = {
        d.requirement_id for d in documents if d.status == ReviewStatus.aceptado and d.requirement_id
    }
    checklist = [
        {
            "requirement_id": str(r.id),
            "name": r.name,
            "required": r.required,
            "delivered": r.id in accepted_by_requirement,
        }
        for r in requirements
        if (r.admission_type is None or r.admission_type == student.admission_type)
    ]
    issued = (
        await session.exec(
            select(IssuedDocument).where(IssuedDocument.student_id == student_id)
        )
    ).all()
    return {
        "student": student.model_dump(mode="json"),
        "checklist": checklist,
        "documents": [d.model_dump(mode="json", exclude={"file_path"}) for d in documents],
        "issued_documents": [d.model_dump(mode="json") for d in issued],
        "overdue_balance": await overdue_balance(session, student_id),
    }


# --- Official documents (RF-D04/D05, RF-T07 blocking) ----------------------------------

async def _student_plan_context(
    session: SessionDep, student: Student, plan_version_id: uuid.UUID | None
) -> dict:
    """RVOE/plan payload for the document (RF-D04 mandatory data)."""
    if plan_version_id is None:
        return {}
    plan = await session.get(PlanVersion, plan_version_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan de estudios no encontrado")
    rvoe = await session.get(Rvoe, plan.rvoe_id)
    program = await session.get(Program, rvoe.program_id)
    return {
        "programa": program.name,
        "nivel": program.level,
        "rvoe": rvoe.agreement_number,
        "modalidad": rvoe.modality,
        "plan_version": plan.version_label,
    }


@router.post("/issue", status_code=201)
async def issue_document(
    session: SessionDep, current_user: ServiciosEscolares, body: IssueDocumentIn
) -> IssuedDocumentPublic:
    student = await session.get(Student, body.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if await has_blocking_debt(session, student):  # RF-T07
        raise HTTPException(
            status_code=409,
            detail="El alumno tiene adeudo vencido; emisión bloqueada (RF-T07)",
        )
    needs_plan = body.kind in (
        IssuedDocumentKind.kardex,
        IssuedDocumentKind.certificado_parcial,
        IssuedDocumentKind.certificado_total,
        IssuedDocumentKind.carta_pasante,
    )
    if needs_plan and body.plan_version_id is None:
        raise HTTPException(status_code=400, detail="plan_version_id es requerido para este documento")
    if body.plan_version_id:
        await require_operable_rvoe(session, body.plan_version_id)  # RT-03

    payload: dict = {
        "alumno": student.full_name,
        "curp": student.curp,
        "matricula": student.enrollment_number,
        "notas": body.notes,
        **(await _student_plan_context(session, student, body.plan_version_id)),
    }
    if body.kind in (IssuedDocumentKind.kardex, IssuedDocumentKind.certificado_parcial,
                     IssuedDocumentKind.certificado_total):
        payload["kardex"] = await kardex_rows(session, student.id, body.plan_version_id)
        payload["progress"] = await curricular_progress(session, student.id, body.plan_version_id)
        if body.kind == IssuedDocumentKind.certificado_total and not payload["progress"]["eligible_for_degree"]:
            raise HTTPException(
                status_code=409, detail="El alumno no ha acreditado el 100% del plan (RF-C08)"
            )

    institution = await get_default_institution(session)
    folio = await next_folio(session, institution.id, body.kind.value)
    issued = IssuedDocument(
        student_id=student.id,
        kind=body.kind,
        folio=folio,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        issued_by=current_user.id,
    )
    session.add(issued)
    audit.record(session, actor=current_user.email, action="document.issued",
                 entity="issued_document", entity_id=folio, detail=body.kind)  # RF-D05
    await session.commit()
    await session.refresh(issued)
    return issued


@router.get("/issued")
async def list_issued(
    session: SessionDep, _: AnyStaff, student_id: uuid.UUID | None = None
) -> list[IssuedDocumentPublic]:
    q = select(IssuedDocument).order_by(IssuedDocument.issued_at.desc())
    if student_id:
        q = q.where(IssuedDocument.student_id == student_id)
    return (await session.exec(q)).all()


# --- Regulations (RF-D06) --------------------------------------------------------------

@router.get("/regulations")
async def list_regulations(session: SessionDep, _: AnyStaff) -> list[RegulationPublic]:
    return (await session.exec(select(Regulation).order_by(Regulation.published_at.desc()))).all()


@router.post("/regulations", status_code=201)
async def publish_regulation(
    session: SessionDep, current_user: ServiciosEscolares, body: RegulationCreate
) -> RegulationPublic:
    institution = await get_default_institution(session)
    current = (
        await session.exec(
            select(Regulation).where(
                Regulation.institution_id == institution.id,
                Regulation.is_current == True,  # noqa: E712
            )
        )
    ).all()
    for regulation in current:
        regulation.is_current = False
        session.add(regulation)
    regulation = Regulation(**body.model_dump(), institution_id=institution.id)
    session.add(regulation)
    audit.record(session, actor=current_user.email, action="regulation.published",
                 entity="regulation", entity_id=body.version)
    await session.commit()
    await session.refresh(regulation)
    return regulation


@router.post("/regulations/{regulation_id}/acceptances", status_code=201)
async def record_acceptance(
    session: SessionDep, current_user: AnyStaff, regulation_id: uuid.UUID, student_id: uuid.UUID
) -> dict:
    if await session.get(Regulation, regulation_id) is None:
        raise HTTPException(status_code=404, detail="Reglamento no encontrado")
    if await session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    dup = (
        await session.exec(
            select(RegulationAcceptance).where(
                RegulationAcceptance.regulation_id == regulation_id,
                RegulationAcceptance.student_id == student_id,
            )
        )
    ).first()
    if dup:
        return {"ok": True, "already_accepted": True}
    session.add(
        RegulationAcceptance(
            regulation_id=regulation_id, student_id=student_id, recorded_by=current_user.id
        )
    )
    audit.record(session, actor=current_user.email, action="regulation.accepted",
                 entity="regulation", entity_id=str(regulation_id), detail=str(student_id))
    await session.commit()
    return {"ok": True, "already_accepted": False}


# --- Teacher expedientes (RF-D07) ---------------------------------------------------------

@router.get("/teachers")
async def list_teacher_profiles(session: SessionDep, _: AnyStaff) -> list[TeacherProfilePublic]:
    return (await session.exec(select(TeacherProfile))).all()


@router.put("/teachers", status_code=201)
async def upsert_teacher_profile(
    session: SessionDep, current_user: ServiciosEscolares, body: TeacherProfileUpsert
) -> TeacherProfilePublic:
    user = await session.get(User, body.user_id)
    if user is None or user.role != UserRole.docente:
        raise HTTPException(status_code=400, detail="El usuario no es docente")
    profile = (
        await session.exec(select(TeacherProfile).where(TeacherProfile.user_id == body.user_id))
    ).first()
    if profile:
        for k, v in body.model_dump(exclude={"user_id"}).items():
            setattr(profile, k, v)
    else:
        profile = TeacherProfile(**body.model_dump())
    session.add(profile)
    audit.record(session, actor=current_user.email, action="teacher_profile.upserted",
                 entity="teacher_profile", entity_id=str(body.user_id))
    await session.commit()
    await session.refresh(profile)
    return profile


@router.post("/teachers/{profile_id}/documents", status_code=201)
async def upload_teacher_document(
    session: SessionDep,
    current_user: ServiciosEscolares,
    profile_id: uuid.UUID,
    file: UploadFile,
    title: str,
) -> TeacherDocumentPublic:
    profile = await session.get(TeacherProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Expediente docente no encontrado")
    path = await save_upload(file, f"teachers/{profile_id}")
    document = TeacherDocument(
        teacher_profile_id=profile_id,
        title=title,
        file_path=path,
        filename=file.filename or "documento",
        content_type=file.content_type or "application/octet-stream",
        uploaded_by=current_user.id,
    )
    session.add(document)
    audit.record(session, actor=current_user.email, action="teacher_document.uploaded",
                 entity="teacher_document", entity_id=str(document.id), detail=title)
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/teachers/{profile_id}/documents")
async def list_teacher_documents(
    session: SessionDep, _: AnyStaff, profile_id: uuid.UUID
) -> list[TeacherDocumentPublic]:
    return (
        await session.exec(
            select(TeacherDocument).where(TeacherDocument.teacher_profile_id == profile_id)
        )
    ).all()
