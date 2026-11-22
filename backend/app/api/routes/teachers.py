"""Profesores: a docente is a user with role docente plus their expediente
(cédula, grado, CV, documentos). Servicios Escolares creates them here — account
and expediente in one step, with the access sent by email — and then assigns them
to a materia in Grupos."""
import html
import secrets
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import EmailStr
from sqlmodel import Field, SQLModel, func, select

from app.api.deps import AnyStaff, ServiciosEscolares, SessionDep
from app.core.security import get_password_hash
from app.models import (
    Campus,
    Group,
    GroupSubject,
    PlanSubject,
    TeacherDocument,
    TeacherProfile,
    Term,
    User,
    UserRole,
)
from app.services import audit
from app.services.email import send_email

router = APIRouter(prefix="/teachers", tags=["teachers"])


class TeacherCreate(SQLModel):
    full_name: str = Field(min_length=3, max_length=255)
    email: EmailStr
    cedula_profesional: str = Field(default="", max_length=32)
    max_degree: str = Field(default="", max_length=128)
    cv_summary: str = Field(default="", max_length=2048)


class TeacherUpdate(SQLModel):
    full_name: str | None = Field(default=None, min_length=3, max_length=255)
    email: EmailStr | None = None
    is_active: bool | None = None
    cedula_profesional: str | None = Field(default=None, max_length=32)
    max_degree: str | None = Field(default=None, max_length=128)
    cv_summary: str | None = Field(default=None, max_length=2048)


def _access_email(name: str, email: str, password: str) -> dict:
    return {
        "subject": "Tu acceso como docente — INUE Escolar",
        "html": (
            f"<p>Hola {html.escape(name)},</p>"
            "<p>Se creó tu acceso a INUE Escolar para pasar lista y capturar calificaciones.</p>"
            f"<p>Usuario: <b>{html.escape(email)}</b><br/>"
            f"Contraseña: <b>{html.escape(password)}</b></p>"
            "<p>Inicia sesión y cambia tu contraseña desde tu perfil.</p>"
        ),
    }


async def _teacher(session, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.role != UserRole.docente:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")
    return user


async def _profile(session, user_id: uuid.UUID) -> TeacherProfile | None:
    return (
        await session.exec(select(TeacherProfile).where(TeacherProfile.user_id == user_id))
    ).first()


async def _campuses_of(session, user_ids: list) -> dict:
    """The planteles where each one teaches now (materias in open cycles). A profesor
    may teach in any plantel; it follows from their classes, not from their account."""
    out: dict = {u: [] for u in user_ids}
    if user_ids:
        for user_id, campus_id, name in (
            await session.exec(
                select(GroupSubject.teacher_user_id, Campus.id, Campus.name)
                .join(Group, Group.id == GroupSubject.group_id)
                .join(Term, Term.id == Group.term_id)
                .join(Campus, Campus.id == Group.campus_id)
                .where(
                    GroupSubject.teacher_user_id.in_(user_ids),  # type: ignore[union-attr]
                    Term.is_open == True,  # noqa: E712
                )
                .distinct()
                .order_by(Campus.name)
            )
        ).all():
            out[user_id].append({"id": str(campus_id), "name": name})
    return out


def _public(user: User, profile: TeacherProfile | None, campuses: list, classes_now: int = 0) -> dict:
    return {
        "id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "is_active": user.is_active,
        "campuses": campuses,
        "profile_id": str(profile.id) if profile else None,
        "cedula_profesional": profile.cedula_profesional if profile else "",
        "max_degree": profile.max_degree if profile else "",
        "cv_summary": profile.cv_summary if profile else "",
        "classes_now": classes_now,  # materias assigned in open cycles
    }


@router.get("")
async def list_teachers(session: SessionDep, _: AnyStaff) -> list[dict]:
    users = (
        await session.exec(select(User).where(User.role == UserRole.docente).order_by(User.full_name))
    ).all()
    ids = [u.id for u in users]
    profiles = {
        p.user_id: p
        for p in (
            await session.exec(select(TeacherProfile).where(TeacherProfile.user_id.in_(ids or [uuid.uuid4()])))  # type: ignore[attr-defined]
        ).all()
    }
    now = dict(
        (
            await session.exec(
                select(GroupSubject.teacher_user_id, func.count())
                .join(Group, Group.id == GroupSubject.group_id)
                .join(Term, Term.id == Group.term_id)
                .where(Term.is_open == True, GroupSubject.teacher_user_id.in_(ids or [uuid.uuid4()]))  # type: ignore[attr-defined]  # noqa: E712
                .group_by(GroupSubject.teacher_user_id)
            )
        ).all()
    )
    campuses = await _campuses_of(session, ids)
    return [_public(u, profiles.get(u.id), campuses[u.id], now.get(u.id, 0)) for u in users]


@router.post("", status_code=201)
async def create_teacher(
    session: SessionDep, current_user: ServiciosEscolares, body: TeacherCreate,
    background: BackgroundTasks,
) -> dict:
    """Account (role docente, generated password sent by email) + expediente."""
    email = body.email.lower()
    if (await session.exec(select(User).where(User.email == email))).first():
        raise HTTPException(status_code=409, detail="Ya hay un usuario con ese correo")
    password = secrets.token_urlsafe(10)
    user = User(
        email=email, full_name=body.full_name.strip(), role=UserRole.docente,
        hashed_password=get_password_hash(password),
    )
    session.add(user)
    await session.flush()
    profile = TeacherProfile(
        user_id=user.id, cedula_profesional=body.cedula_profesional.strip(),
        max_degree=body.max_degree.strip(), cv_summary=body.cv_summary.strip(),
    )
    session.add(profile)
    audit.record(session, actor=current_user.email, action="teacher.created",
                 entity="user", entity_id=str(user.id), detail=email)
    await session.commit()
    await session.refresh(user)
    await session.refresh(profile)
    background.add_task(send_email, to=email, **_access_email(user.full_name, email, password))
    return _public(user, profile, (await _campuses_of(session, [user.id]))[user.id])


@router.get("/{user_id}")
async def get_teacher(session: SessionDep, _: AnyStaff, user_id: uuid.UUID) -> dict:
    """Ficha: datos, expediente, documentos y sus clases (newest cycle first)."""
    user = await _teacher(session, user_id)
    profile = await _profile(session, user_id)
    classes = [
        {
            "group_subject_id": str(gs.id), "group_id": str(g.id), "group_code": g.code,
            "subject": f"{ps.code} — {ps.name}", "period_number": ps.period_number,
            "term_name": t.name, "term_open": t.is_open, "campus": c.name,
            "schedule": gs.schedule_text,
        }
        for gs, g, ps, t, c in (
            await session.exec(
                select(GroupSubject, Group, PlanSubject, Term, Campus)
                .join(Group, Group.id == GroupSubject.group_id)
                .join(PlanSubject, PlanSubject.id == GroupSubject.plan_subject_id)
                .join(Term, Term.id == Group.term_id)
                .join(Campus, Campus.id == Group.campus_id)
                .where(GroupSubject.teacher_user_id == user_id)
                .order_by(Term.start_date.desc(), Group.code, PlanSubject.code)  # type: ignore[attr-defined]
            )
        ).all()
    ]
    documents = []
    if profile is not None:
        documents = [
            {"id": str(d.id), "title": d.title, "filename": d.filename,
             "uploaded_at": d.uploaded_at.isoformat()}
            for d in (
                await session.exec(
                    select(TeacherDocument)
                    .where(TeacherDocument.teacher_profile_id == profile.id)
                    .order_by(TeacherDocument.uploaded_at.desc())  # type: ignore[attr-defined]
                )
            ).all()
        ]
    out = _public(
        user, profile, (await _campuses_of(session, [user.id]))[user.id],
        sum(1 for c in classes if c["term_open"]),
    )
    return {**out, "classes": classes, "documents": documents}


@router.patch("/{user_id}")
async def update_teacher(
    session: SessionDep, current_user: ServiciosEscolares, user_id: uuid.UUID, body: TeacherUpdate,
) -> dict:
    user = await _teacher(session, user_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("email"):
        email = str(changes["email"]).lower()
        clash = (await session.exec(select(User).where(User.email == email, User.id != user.id))).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ya hay un usuario con ese correo")
        user.email = email
    if changes.get("full_name"):
        user.full_name = changes["full_name"].strip()
    if changes.get("is_active") is not None:
        user.is_active = changes["is_active"]
    session.add(user)
    profile = await _profile(session, user_id) or TeacherProfile(user_id=user.id)
    for key in ("cedula_profesional", "max_degree", "cv_summary"):
        if changes.get(key) is not None:
            setattr(profile, key, changes[key].strip())
    session.add(profile)
    audit.record(session, actor=current_user.email, action="teacher.updated",
                 entity="user", entity_id=str(user.id),
                 detail=", ".join(sorted(k for k in changes if k != "cv_summary")))
    await session.commit()
    return await get_teacher(session, current_user, user_id)


@router.get("/documents/{document_id}/file")
async def download_teacher_document(session: SessionDep, _: AnyStaff, document_id: uuid.UUID) -> FileResponse:
    document = await session.get(TeacherDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return FileResponse(document.file_path, media_type=document.content_type, filename=document.filename)
