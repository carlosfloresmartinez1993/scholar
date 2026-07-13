"""User management (RT-07): superuser manages staff accounts; each account has
a granular role (servicios escolares, tesorería, coordinación, docente…)."""
import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import AnyStaff, SessionDep, SuperUser
from app.core.security import get_password_hash
from app.models import User, UserCreate, UserPublic, UserRole, UserUpdate
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(
    session: SessionDep, _: AnyStaff, role: UserRole | None = None
) -> list[UserPublic]:
    q = select(User).order_by(User.created_at)
    if role:
        q = q.where(User.role == role)
    return (await session.exec(q)).all()


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
    audit.record(session, actor=actor.email, action="user.created", entity="user",
                 detail=f"{body.email} ({body.role})")
    await session.commit()
    await session.refresh(user)
    return user


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
    for k, v in changes.items():
        setattr(user, k, v)
    session.add(user)
    audit.record(session, actor=actor.email, action="user.updated", entity="user",
                 entity_id=str(user_id), detail=", ".join(changes.keys()))
    await session.commit()
    await session.refresh(user)
    return user


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
