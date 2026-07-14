"""Security utilities: password hashing, cookie-JWT, integration API key."""
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED

from app.core.config import settings

password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))

ALGORITHM = "HS256"


class OAuth2PasswordBearerWithCookie(OAuth2PasswordBearer):
    """Reads the Bearer token from the 'access_token' cookie.

    The Authorization header is intentionally ignored, cookie takes precedence.
    """

    async def __call__(self, request: Request) -> Optional[str]:
        authorization: str = request.cookies.get("access_token")
        scheme, param = get_authorization_scheme_param(authorization)
        if not authorization or scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        return param


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(
        {"exp": expire, "sub": str(subject), "type": "access"},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_refresh_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(
        {"exp": expire, "sub": str(subject), "type": "refresh"},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type — expected {expected_type}",
        )
    return payload


def verify_password(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def verify_integration_key(provided: str | None) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(provided, settings.INTEGRATION_API_KEY)
