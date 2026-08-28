import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import OAuth2PasswordBearerWithCookie, decode_token, verify_integration_key
from app.models import Campus, User, UserCampus, UserPublic, UserRole

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

# Roles that may already see a NAMED student's balance: tesorería through the
# statement (TreasuryStaff), academic staff through the expediente, which
# carries overdue_balance. UserRole.docente is deliberately absent from both, so
# it is absent here — a teacher can read the students list, and that list must
# not become the one place a teacher learns what every student owes.
STAFF_FINANCIAL = STAFF_ACADEMIC + (UserRole.tesoreria,)


def can_read_debt(user: User) -> bool:
    return user.is_superuser or user.role in STAFF_FINANCIAL


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


# --- Campus scope (membership axis, orthogonal to role) ------------------------

def is_all_campus(user: User) -> bool:
    """Superusers and admin_sistema see every campus, no membership rows needed."""
    return user.is_superuser or user.role == UserRole.admin_sistema


async def _member_campus_ids(session: AsyncSession, user: User) -> list[uuid.UUID]:
    rows = await session.exec(
        select(UserCampus.campus_id).where(UserCampus.user_id == user.id)
    )
    return list(rows.all())


async def _all_campus_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.exec(select(Campus.id))
    return list(rows.all())


async def build_users_public(session: AsyncSession, users: list[User]) -> list[UserPublic]:
    """Batch variant of build_user_public: one membership query for the whole
    list instead of one per user (the users admin lists everyone)."""
    if not users:
        return []
    all_ids = await _all_campus_ids(session)
    rows = await session.exec(
        select(UserCampus.user_id, UserCampus.campus_id).where(
            UserCampus.user_id.in_([u.id for u in users])
        )
    )
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for uid, cid in rows.all():
        members.setdefault(uid, []).append(cid)
    out: list[UserPublic] = []
    for u in users:
        public = UserPublic.model_validate(u, from_attributes=True)
        if is_all_campus(u):
            public.campuses = list(all_ids)
            public.all_campuses = True
        else:
            public.campuses = members.get(u.id, [])
            public.all_campuses = False
        out.append(public)
    return out


async def build_user_public(session: AsyncSession, user: User) -> UserPublic:
    """UserPublic with the computed campus scope filled in (for /auth/me and the
    users admin so the frontend knows which campuses to offer)."""
    public = UserPublic.model_validate(user, from_attributes=True)
    if is_all_campus(user):
        public.campuses = await _all_campus_ids(session)
        public.all_campuses = True
    else:
        public.campuses = await _member_campus_ids(session, user)
        public.all_campuses = False
    return public


async def active_campus(
    request: Request, session: SessionDep, current_user: CurrentUser
) -> list[uuid.UUID] | None:
    """Resolve the request's campus scope from the X-Campus header.

    Returns None (unrestricted) for all-campus users and for the "all view";
    otherwise the list of campus ids the query/write must be confined to. A
    specific X-Campus id is 403 unless the user is all-campus or a member."""
    header = request.headers.get("X-Campus")
    all_campus = is_all_campus(current_user)
    if header and header != "__all__":
        try:
            requested = uuid.UUID(header)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Plantel inválido"
            ) from err
        if all_campus:
            return [requested]
        if requested not in await _member_campus_ids(session, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a ese plantel"
            )
        return [requested]
    # header absent or "__all__": all-campus users are unrestricted, members are
    # confined to every campus they belong to.
    if all_campus:
        return None
    return await _member_campus_ids(session, current_user)


CampusScope = Annotated[list[uuid.UUID] | None, Depends(active_campus)]


def ensure_in_scope(scope: list[uuid.UUID] | None, campus_id: uuid.UUID) -> None:
    """Guard a create/update: raise 403 when the target campus is outside scope.
    scope None = unrestricted (all-campus user or all-view)."""
    if scope is not None and campus_id not in scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a ese plantel"
        )
