"""Student portal access: create/reactivate the linked alumno account with a
generated password and build the credentials email. Caller commits and queues
the email AFTER a successful commit (the password never travels in an API
response)."""
import html
import secrets

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_password_hash
from app.models import Student, User, UserRole
from app.services import audit


async def grant_portal_access(
    session: AsyncSession, student: Student, actor: str
) -> tuple[User, str]:
    """Create (or reactivate) the alumno account for a student. Returns the
    user and the plaintext generated password (for the credentials email).
    Does not commit."""
    email = (student.email or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=409, detail="El alumno no tiene email registrado"
        )
    password = secrets.token_urlsafe(10)
    linked = (
        await session.exec(select(User).where(User.student_id == student.id))
    ).first()
    if linked is not None and linked.is_active:
        raise HTTPException(
            status_code=409, detail="El alumno ya tiene acceso a la plataforma"
        )
    if linked is not None and linked.role != UserRole.alumno:
        # never reset/email credentials for an account promoted to a staff role
        raise HTTPException(
            status_code=409, detail="La cuenta vinculada ya no es una cuenta de alumno"
        )
    # a DIFFERENT account with that email blocks the grant
    dup = (await session.exec(select(User).where(User.email == email))).first()
    if dup is not None and (linked is None or dup.id != linked.id):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")
    if linked is not None:
        # reactivate with a fresh password (the old one is gone by design)
        linked.is_active = True
        linked.email = email
        linked.hashed_password = get_password_hash(password)
        user = linked
        action = "portal_access.reactivated"
    else:
        user = User(
            email=email,
            full_name=student.full_name,
            role=UserRole.alumno,
            student_id=student.id,
            hashed_password=get_password_hash(password),
        )
        action = "portal_access.granted"
    session.add(user)
    await session.flush()
    audit.record(session, actor=actor, action=action,
                 entity="student", entity_id=str(student.id), detail=email)
    return user, password


def credentials_email(student_name: str, email: str, password: str) -> dict:
    """Subject + HTML for the portal credentials email (password included —
    this is the only place it travels)."""
    safe_name = html.escape(student_name)
    return {
        "subject": "Tu acceso a la plataforma — INUE Escolar",
        "html": (
            f"<p>Hola {safe_name},</p>"
            f"<p>Se habilitó tu acceso al portal de alumnos.</p>"
            f"<p>Usuario: <b>{html.escape(email)}</b><br/>"
            f"Contraseña: <b>{html.escape(password)}</b></p>"
            f"<p>Inicia sesión y cambia tu contraseña desde tu perfil.</p>"
        ),
    }
