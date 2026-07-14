import logging
import time
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

logger = logging.getLogger(__name__)

# Login throttling: after MAX_FAILED_ATTEMPTS failures for the same IP+account,
# lock out with exponential backoff. In-memory, per-process.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_BASE_SECONDS = 30
LOCKOUT_MAX_SECONDS = 900
FAILED_ATTEMPT_TTL_SECONDS = 900

# key -> (failure_count, locked_until, last_failure); times from time.monotonic()
_failed_logins: dict[str, tuple[int, float, float]] = {}


def _throttle_key(request: Request, email: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{email}"


def _prune_failed_logins(now: float) -> None:
    stale = [
        key
        for key, (_, locked_until, last_failure) in _failed_logins.items()
        if now - last_failure > FAILED_ATTEMPT_TTL_SECONDS and now >= locked_until
    ]
    for key in stale:
        del _failed_logins[key]


def _check_login_lockout(key: str) -> None:
    entry = _failed_logins.get(key)
    if not entry:
        return
    _, locked_until, _ = entry
    now = time.monotonic()
    if now < locked_until:
        retry_after = int(locked_until - now) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )


def _record_failed_login(key: str) -> None:
    now = time.monotonic()
    _prune_failed_logins(now)
    count = _failed_logins.get(key, (0, 0.0, 0.0))[0] + 1
    locked_until = 0.0
    if count >= MAX_FAILED_ATTEMPTS:
        locked_until = now + min(
            LOCKOUT_BASE_SECONDS * 2 ** (count - MAX_FAILED_ATTEMPTS),
            LOCKOUT_MAX_SECONDS,
        )
    _failed_logins[key] = (count, locked_until, now)
    logger.warning("Failed login attempt %d for %s", count, key)


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
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> UserPublic:
    email = form_data.username.lower()
    key = _throttle_key(request, email)
    _check_login_lockout(key)
    result = await session.exec(select(User).where(User.email == email))
    user = result.first()
    if not user:
        _record_failed_login(key)
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    ok, new_hash = verify_password(form_data.password, user.hashed_password)
    if not ok:
        _record_failed_login(key)
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if new_hash:
        user.hashed_password = new_hash
        session.add(user)
        await session.commit()
    _failed_logins.pop(key, None)
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
