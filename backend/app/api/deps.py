import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import OAuth2PasswordBearerWithCookie, decode_token, verify_integration_key
from app.models import User, UserRole

reusable_oauth2 = OAuth2PasswordBearerWithCookie(tokenUrl=f"{settings.API_V1_STR}/auth/login")

TokenDep = Annotated[str, Depends(reusable_oauth2)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(session: SessionDep, token: TokenDep) -> User:
    payload = decode_token(token)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Token")

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Token")
    result = await session.exec(select(User).where(User.id == user_uuid))
    user = result.first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
    return user


async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
SuperUser = Annotated[User, Depends(get_current_active_superuser)]


def require_roles(*roles: UserRole):
    """RT-07: allow only the given staff roles (superusers always pass)."""

    async def checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.is_superuser or current_user.role in roles:
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")

    return checker


# Common role bundles. NOTE: these are EXPLICIT lists — UserRole.alumno is
# deliberately absent from every one of them, so portal accounts can never
# reach staff endpoints (superusers are staff by definition and always pass).
STAFF_ACADEMIC = (
    UserRole.admin_sistema,
    UserRole.direccion,
    UserRole.servicios_escolares,
    UserRole.coordinador_academico,
)
STAFF_ALL = STAFF_ACADEMIC + (UserRole.tesoreria, UserRole.docente)

ServiciosEscolares = Annotated[
    User, Depends(require_roles(UserRole.admin_sistema, UserRole.direccion, UserRole.servicios_escolares))
]
AcademicStaff = Annotated[User, Depends(require_roles(*STAFF_ACADEMIC))]
AnyStaff = Annotated[User, Depends(require_roles(*STAFF_ALL))]
TreasuryStaff = Annotated[
    User, Depends(require_roles(UserRole.admin_sistema, UserRole.direccion, UserRole.tesoreria))
]
# Authorizes actions requiring management sign-off (e.g. scholarship approval).
Authorizer = Annotated[
    User, Depends(require_roles(UserRole.admin_sistema, UserRole.direccion))
]
TeacherOrAcademic = Annotated[
    User, Depends(require_roles(*STAFF_ACADEMIC, UserRole.docente))
]


async def get_current_student_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Portal guard: ONLY role=alumno accounts linked to a student row pass —
    staff (including superusers) get 403; the portal is strictly self-scoped."""
    if current_user.role != UserRole.alumno or current_user.student_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
    return current_user


CurrentStudentUser = Annotated[User, Depends(get_current_student_user)]


async def verify_integration_api_key(request: Request) -> None:
    """RT-11: the calendar system authenticates with X-API-Key."""
    if not verify_integration_key(request.headers.get("X-API-Key")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
