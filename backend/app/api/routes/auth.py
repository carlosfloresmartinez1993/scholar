import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models import User, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_PATH = f"{settings.API_V1_STR}/auth/refresh"


def _set_auth_cookies(response: Response, user_id: str) -> None:
    secure = settings.ENVIRONMENT != "local"
    access = create_access_token(
        user_id, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh = create_refresh_token(
        user_id, timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    )
    response.set_cookie(
        "access_token",
        f"Bearer {access}",
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        "refresh_token",
        refresh,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=REFRESH_PATH,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login")
async def login(
    session: SessionDep,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> UserPublic:
    result = await session.exec(select(User).where(User.email == form_data.username.lower()))
    user = result.first()
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    ok, new_hash = verify_password(form_data.password, user.hashed_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if new_hash:
        user.hashed_password = new_hash
        session.add(user)
        await session.commit()
    _set_auth_cookies(response, str(user.id))
    return user


@router.post("/refresh")
async def refresh(session: SessionDep, request: Request, response: Response) -> UserPublic:
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    payload = decode_token(token, expected_type="refresh")
    result = await session.exec(select(User).where(User.id == uuid.UUID(payload["sub"])))
    user = result.first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    _set_auth_cookies(response, str(user.id))
    return user


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token", path=REFRESH_PATH)
    return {"ok": True}


@router.get("/me")
async def me(current_user: CurrentUser) -> UserPublic:
    return current_user


from pydantic import BaseModel, Field as PydanticField  # noqa: E402


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = PydanticField(min_length=8, max_length=128)


@router.post("/change-password")
async def change_password(
    session: SessionDep, current_user: CurrentUser, body: PasswordChangeIn
) -> dict:
    ok, _ = verify_password(body.current_password, current_user.hashed_password)
    if not ok:
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    current_user.hashed_password = get_password_hash(body.new_password)
    session.add(current_user)
    await session.commit()
    return {"ok": True}
