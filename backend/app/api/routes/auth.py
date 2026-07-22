import hashlib
import hmac
import logging
import secrets
import time
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, build_user_public
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models import User, UserPublic
from app.models.common import utcnow
from app.services.email import send_email

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
    return await build_user_public(session, user)


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
    return await build_user_public(session, user)


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token", path=REFRESH_PATH)
    return {"ok": True}


@router.get("/me")
async def me(session: SessionDep, current_user: CurrentUser) -> UserPublic:
    return await build_user_public(session, current_user)


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

# --- Login por código de correo -------------------------------------------------------
# Same session cookies as the password login; the 6-digit code travels only by
# email and only its sha256 lands in the DB. Reuses the login lockout machinery.

LOGIN_CODE_TTL_MINUTES = 10
LOGIN_CODE_RESEND_SECONDS = 60


def _login_code_digest(code: str) -> str:
    """Keyed digest: a bare sha256 of a 6-digit code is brute-forceable offline
    by anyone who can read the DB; keying with SECRET_KEY closes that."""
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


class LoginCodeRequest(BaseModel):
    email: str


class LoginCodeVerify(BaseModel):
    email: str
    code: str = PydanticField(min_length=6, max_length=6)


@router.post("/login-code/request")
async def request_login_code(
    session: SessionDep, body: LoginCodeRequest, background: BackgroundTasks
) -> dict:
    """Email a one-time 6-digit login code. Always returns ok — the response
    never reveals whether the account exists."""
    # Row lock: two concurrent requests must not each store a different code
    # (one emailed code would silently be dead). No-op on sqlite tests.
    result = await session.exec(
        select(User).where(User.email == body.email.lower()).with_for_update()
    )
    user = result.first()
    if user and user.is_active:
        now = utcnow()
        if (
            user.login_code_sent_at is not None
            and (now - user.login_code_sent_at).total_seconds() < LOGIN_CODE_RESEND_SECONDS
        ):
            # Silently suppress the resend: a 429 here would distinguish real
            # accounts from unknown ones (which always get 200).
            return {"ok": True}
        code = f"{secrets.randbelow(1_000_000):06d}"
        user.login_code_hash = _login_code_digest(code)
        user.login_code_expires = now + timedelta(minutes=LOGIN_CODE_TTL_MINUTES)
        user.login_code_sent_at = now
        session.add(user)
        await session.commit()
        background.add_task(
            send_email,
            to=user.email,
            subject="Tu código de acceso — INUE Escolar",
            html=(
                "<p>Tu código para iniciar sesión es:</p>"
                f"<p style='font-size:24px;font-weight:bold;letter-spacing:4px'>{code}</p>"
                f"<p>Expira en {LOGIN_CODE_TTL_MINUTES} minutos. "
                "Si no lo solicitaste, ignora este mensaje.</p>"
            ),
        )
    return {"ok": True}


@router.post("/login-code/verify")
async def verify_login_code(
    session: SessionDep, request: Request, response: Response, body: LoginCodeVerify
) -> UserPublic:
    key = _throttle_key(request, body.email.lower())
    # Also lock per-account: distributed source IPs must share one attempt
    # budget for a 6-digit keyspace, not get a fresh budget each.
    acct_key = f"acct:{body.email.lower()}"
    _check_login_lockout(key)
    _check_login_lockout(acct_key)
    # Lock the row so exactly one concurrent verification can consume the code.
    result = await session.exec(
        select(User).where(User.email == body.email.lower()).with_for_update()
    )
    user = result.first()
    invalid = HTTPException(status_code=400, detail="Código incorrecto o expirado")
    if not user or not user.is_active or not user.login_code_hash:
        _record_failed_login(key)
        _record_failed_login(acct_key)
        raise invalid
    if user.login_code_expires is None or utcnow() > user.login_code_expires:
        _record_failed_login(key)
        _record_failed_login(acct_key)
        raise invalid
    submitted = _login_code_digest(body.code)
    if not hmac.compare_digest(submitted, user.login_code_hash):
        _record_failed_login(key)
        _record_failed_login(acct_key)
        raise invalid
    # single-use: burn the code before issuing the session
    user.login_code_hash = None
    user.login_code_expires = None
    session.add(user)
    await session.commit()
    _failed_logins.pop(key, None)
    _failed_logins.pop(acct_key, None)
    _set_auth_cookies(response, str(user.id))
    return await build_user_public(session, user)

