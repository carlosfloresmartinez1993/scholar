"""User management (RT-07): superuser manages staff accounts; each account has
a granular role (servicios escolares, tesorería, coordinación, docente…).
Also self-service profile settings (display name, position, recovery email)."""
import hashlib
import hmac
import html
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlmodel import select

from app.api.deps import (
    AnyStaff,
    CurrentUser,
    SessionDep,
    SuperUser,
    build_user_public,
    build_users_public,
)
from app.core.security import get_password_hash, verify_password
from app.models import (
    ProfileUpdate,
    RecoveryEmailRequest,
    RecoveryEmailVerify,
    User,
    UserCampus,
    UserCreate,
    UserPublic,
    UserRole,
    UserUpdate,
)
from app.models.common import utcnow
from app.services import audit
from app.services.email import send_email

router = APIRouter(prefix="/users", tags=["users"])

RECOVERY_CODE_TTL_MINUTES = 10
RECOVERY_RESEND_SECONDS = 60


# --- Self-service profile (current user) --------------------------------------

@router.patch("/me/profile")
async def update_my_profile(
    session: SessionDep, current_user: CurrentUser, body: ProfileUpdate
) -> UserPublic:
    changes = body.model_dump(exclude_unset=True)
    # never a real attribute — only used to authorize an email change below
    current_password = changes.pop("current_password", None)
    if "email" in changes:
        if changes["email"] is None:
            raise HTTPException(status_code=422, detail="El email no puede quedar vacío")
        new_email = changes["email"].lower()
        if new_email != current_user.email:
            # changing the login email requires re-entering the password
            if not current_password:
                raise HTTPException(status_code=403, detail="Contraseña incorrecta")
            ok, _ = verify_password(current_password, current_user.hashed_password)
            if not ok:
                raise HTTPException(status_code=403, detail="Contraseña incorrecta")
            dup = (await session.exec(select(User).where(User.email == new_email))).first()
            if dup:
                raise HTTPException(status_code=409, detail="Email already registered")
        changes["email"] = new_email
    for k, v in changes.items():
        setattr(current_user, k, v)
    session.add(current_user)
    audit.record(session, actor=current_user.email, action="user.profile_updated",
                 entity="user", entity_id=str(current_user.id),
                 detail=", ".join(changes.keys()))
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.post("/me/recovery-email/request")
async def request_recovery_email(
    session: SessionDep,
    current_user: CurrentUser,
    body: RecoveryEmailRequest,
    background: BackgroundTasks,
) -> dict:
    """Send a 6-digit verification code to the given recovery email. Also the
    resend path: same endpoint, throttled to one send per minute."""
    now = utcnow()
    if (
        current_user.recovery_code_sent_at is not None
        and (now - current_user.recovery_code_sent_at).total_seconds()
        < RECOVERY_RESEND_SECONDS
    ):
        raise HTTPException(
            status_code=429,
            detail="Espera un minuto antes de solicitar otro código",
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    # The candidate address stays pending; the verified one is untouched until
    # the code checks out.
    current_user.pending_recovery_email = body.email.lower()
    current_user.recovery_code_hash = hashlib.sha256(code.encode()).hexdigest()
    current_user.recovery_code_expires = now + timedelta(minutes=RECOVERY_CODE_TTL_MINUTES)
    current_user.recovery_code_sent_at = now
    session.add(current_user)
    audit.record(session, actor=current_user.email, action="user.recovery_email_requested",
                 entity="user", entity_id=str(current_user.id))
    await session.commit()
    # The code travels only by email — never in the API response.
    safe_name = html.escape(current_user.display_name or current_user.full_name)
    background.add_task(
        send_email,
        to=current_user.pending_recovery_email,
        subject="Código de verificación — INUE Escolar",
        html=(
            f"<p>Hola {safe_name},</p>"
            f"<p>Tu código para verificar el correo de recuperación es:</p>"
            f"<p style='font-size:24px;font-weight:bold;letter-spacing:4px'>{code}</p>"
            f"<p>Vence en {RECOVERY_CODE_TTL_MINUTES} minutos. Si no lo "
            f"solicitaste, ignora este mensaje.</p>"
        ),
    )
    return {"ok": True}


@router.post("/me/recovery-email/verify")
async def verify_recovery_email(
    session: SessionDep, current_user: CurrentUser, body: RecoveryEmailVerify
) -> UserPublic:
    if not current_user.recovery_code_hash or current_user.recovery_code_expires is None:
        raise HTTPException(status_code=400, detail="No hay un código pendiente de verificar")
    if utcnow() > current_user.recovery_code_expires:
        raise HTTPException(status_code=400, detail="El código expiró; solicita uno nuevo")
    submitted = hashlib.sha256(body.code.encode()).hexdigest()
    if not hmac.compare_digest(submitted, current_user.recovery_code_hash):
        raise HTTPException(status_code=400, detail="Código incorrecto")
    # promote the pending address now that its code checked out
    current_user.recovery_email = current_user.pending_recovery_email
    current_user.recovery_email_verified = True
    current_user.pending_recovery_email = None
    current_user.recovery_code_hash = None
    current_user.recovery_code_expires = None
    current_user.recovery_code_sent_at = None
    session.add(current_user)
    audit.record(session, actor=current_user.email, action="user.recovery_email_verified",
                 entity="user", entity_id=str(current_user.id))
    await session.commit()
    await session.refresh(current_user)
    return current_user


async def _set_campus_membership(
    session: SessionDep, user_id: uuid.UUID, campus_ids: list[uuid.UUID]
) -> None:
    """Replace a user's whole campus membership set (admin write)."""
    existing = (
        await session.exec(select(UserCampus).where(UserCampus.user_id == user_id))
    ).all()
    for row in existing:
        await session.delete(row)
    await session.flush()  # deletes first, or re-adding a kept campus hits the PK
    for campus_id in dict.fromkeys(campus_ids):  # de-dupe, keep order
        session.add(UserCampus(user_id=user_id, campus_id=campus_id))


@router.get("")
async def list_users(
    session: SessionDep, _: AnyStaff, role: UserRole | None = None
) -> list[UserPublic]:
    q = select(User).order_by(User.created_at)
    if role:
        q = q.where(User.role == role)
    users = (await session.exec(q)).all()
    return await build_users_public(session, list(users))


@router.post("", status_code=201)
async def create_user(session: SessionDep, actor: SuperUser, body: UserCreate) -> UserPublic:
    existing = (await session.exec(select(User).where(User.email == body.email.lower()))).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        role=body.role,
        is_active=body.is_active,
        is_superuser=body.is_superuser,
        hashed_password=get_password_hash(body.password),
    )
    session.add(user)
    await session.flush()
    if body.campuses is not None:
        await _set_campus_membership(session, user.id, body.campuses)
    audit.record(session, actor=actor.email, action="user.created", entity="user",
                 detail=f"{body.email} ({body.role})")
    await session.commit()
    await session.refresh(user)
    return await build_user_public(session, user)


@router.patch("/{user_id}")
async def update_user(
    session: SessionDep, actor: SuperUser, user_id: uuid.UUID, body: UserUpdate
) -> UserPublic:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    changes = body.model_dump(exclude_unset=True)
    if "password" in changes:
        password = changes.pop("password")
        if password:
            user.hashed_password = get_password_hash(password)
    if "email" in changes and changes["email"]:
        changes["email"] = changes["email"].lower()
    # campuses is a membership set, not a User column — apply it separately
    campuses = changes.pop("campuses", None)
    for k, v in changes.items():
        setattr(user, k, v)
    session.add(user)
    if campuses is not None:
        await _set_campus_membership(session, user.id, campuses)
        changes["campuses"] = campuses  # for the audit detail
    audit.record(session, actor=actor.email, action="user.updated", entity="user",
                 entity_id=str(user_id), detail=", ".join(changes.keys()))
    await session.commit()
    await session.refresh(user)
    return await build_user_public(session, user)


@router.delete("/{user_id}")
async def deactivate_user(session: SessionDep, actor: SuperUser, user_id: uuid.UUID) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta")
    user.is_active = False
    session.add(user)
    audit.record(session, actor=actor.email, action="user.deactivated", entity="user",
                 entity_id=str(user_id), detail=user.email)
    await session.commit()
    return {"ok": True}
