import uuid
from contextvars import ContextVar
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
    await ensure_not_on_leave(session, user)  # an open session ends when they are dado de baja
    return user


ON_LEAVE_DETAIL = (
    "Tu acceso está suspendido porque estás dado de baja. Acude a Servicios Escolares."
)


async def ensure_not_on_leave(session, user: User) -> None:
    """A student de baja (temporal or definitiva) can't use the system; staff can."""
    if user.student_id is None:
        return
    from app.models import Student, StudentStatus

    student = await session.get(Student, user.student_id)
    if student is not None and student.status in (
        StudentStatus.baja_temporal, StudentStatus.baja_definitiva,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ON_LEAVE_DETAIL)


async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
SuperUser = Annotated[User, Depends(get_current_active_superuser)]


def require_roles(*roles: UserRole):
    """Allow only the given role codes (superusers always pass). Kept for the few
    places that are about who a user IS, not what they may open."""

    async def checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.is_superuser or current_user.role in roles:
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")

    return checker


# --- Permissions by view (Administración → Roles) --------------------------------
# Every staff endpoint names the views that may use it; the role's permissions are
# read from the database on each request, so a change in Roles applies at once.

# own_subjects_only of this request's role (a docente: only their materias)
_own_subjects: ContextVar[bool] = ContextVar("own_subjects", default=False)


async def _role_access(request: Request, session: AsyncSession, user: User) -> tuple[set[str], bool, str]:
    cached = getattr(request.state, "access", None)
    if cached is None:
        from app.services.roles import access_of

        cached = await access_of(session, user)
        request.state.access = cached
    return cached


def require_view(*views: str, any_view: bool = False, staff_only: bool = False):
    """Pass if the user's role grants one of `views` (or, with any_view, any view at
    all). staff_only keeps out roles limited to their own materias (docentes)."""

    async def checker(
        request: Request, session: SessionDep,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role == UserRole.alumno:  # portal accounts never reach staff screens
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough privileges")
        permissions, own, _ = await _role_access(request, session, current_user)
        _own_subjects.set(own)
        allowed = bool(permissions) if any_view else bool(permissions & set(views))
        if staff_only and own:
            allowed = False
        if not allowed:
            only_reads = any(v.endswith(".editar") for v in views) and bool(
                permissions & {v.removesuffix(".editar") for v in views}
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("Tu rol solo puede ver esta sección, no modificarla" if only_reads
                        else "Tu rol no tiene permiso para esta acción"),
            )
        return current_user

    return checker


def View(*views: str, staff_only: bool = False):
    return Annotated[User, Depends(require_view(*views, staff_only=staff_only))]


# office staff: any view, not limited to their own materias (general reference data)
AnyStaff = Annotated[User, Depends(require_view(any_view=True, staff_only=True))]
# any staff role, docentes included (then limited to their own materias)
StaffOrTeacher = Annotated[User, Depends(require_view(any_view=True))]

# one per screen (or group of screens that share the data)
CanInicio = View("inicio")
CanAlumnos = View("alumnos")
CanStudentsRead = View("alumnos", "inscripciones", "grupos", "tesoreria", "egresados", "reportes",
                       staff_only=True)
CanKardexRead = View("alumnos", "egresados", "reportes", "inscripciones", "grupos", staff_only=True)
CanInscripciones = View("inscripciones", "alumnos")
CanEnrollmentChanges = View("grupos", "alumnos", "inscripciones", staff_only=True)
CanProfesores = View("profesores")
CanUsersRead = View("usuarios", "grupos", "profesores", staff_only=True)
CanProgramas = View("programas")
CanGrupos = View("grupos", staff_only=True)
CanGrid = View("calificaciones", "asistencias", "grupos")
CanEgresados = View("egresados")
CanAlumniRead = View("egresados", "reportes", "alumnos", staff_only=True)
CanCalificaciones = View("calificaciones")
CanActas = View("calificaciones", staff_only=True)
CanAsistencias = View("asistencias")
CanAsistenciasStaff = View("asistencias", staff_only=True)
CanJustificaciones = View("asistencias", "alumnos", staff_only=True)
CanTesoreria = View("tesoreria")
CanTesoreriaReports = View("tesoreria", "reportes")
CanBecasAutorizar = View("becas_autorizar")
CanReportes = View("reportes", "alumnos", staff_only=True)
CanPeriodos = View("periodos")
CanPlanteles = View("planteles")
CanConfiguracion = View("configuracion")
CanUsuarios = View("usuarios")
CanAuditoria = View("auditoria")
CanRoles = View("roles")
CanRolesRead = View("roles", "usuarios")

# Etapa 2 — changing something needs «<view>.editar»; delicate actions, their own
CanAlumnosEdit = View("alumnos.editar")
CanInscripcionesEdit = View("inscripciones.editar", "alumnos.editar")
CanEnrollmentChangesEdit = View("grupos.editar", "alumnos.editar", "inscripciones.editar",
                                staff_only=True)
CanProfesoresEdit = View("profesores.editar")
CanProgramasEdit = View("programas.editar")
CanGruposEdit = View("grupos.editar", staff_only=True)
CanEgresadosEdit = View("egresados.editar")
CanCalificacionesEdit = View("calificaciones.editar")
CanAsistenciasEdit = View("asistencias.editar")
CanAsistenciasStaffEdit = View("asistencias.editar", staff_only=True)
CanJustificacionesEdit = View("asistencias.editar", "alumnos.editar", staff_only=True)
CanTesoreriaEdit = View("tesoreria.editar")
CanPeriodosEdit = View("periodos.editar")
CanPlantelesEdit = View("planteles.editar")
CanConfiguracionEdit = View("configuracion.editar")
CanUsuariosEdit = View("usuarios.editar")
CanRolesEdit = View("roles.editar")
CanKardexCorregir = View("kardex_corregir", staff_only=True)
CanRvoeCambio = View("rvoe_cambio", staff_only=True)
CanPromocionCiclo = View("promocion_ciclo", staff_only=True)
CanActasFirmar = View("actas", staff_only=True)
CanPagosCancelar = View("pagos_cancelar")


def own_subjects_only() -> bool:
    """This request's role sees only the materias assigned to its users."""
    return _own_subjects.get()


def is_teacher(user: User) -> bool:  # kept name: «limited to their own materias»
    return own_subjects_only() and not user.is_superuser


def ensure_own_subject(user: User, group_subject) -> None:
    """A role limited to its own materias only reaches those assigned to the user."""
    if is_teacher(user) and group_subject.teacher_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes asignada esta materia")


# Roles that may already see a NAMED student's balance: tesorería through the
# statement (TreasuryStaff), academic staff through the expediente, which
# carries overdue_balance. UserRole.docente is deliberately absent from both, so
# it is absent here — a teacher can read the students list, and that list must
# not become the one place a teacher learns what every student owes.
STAFF_FINANCIAL = (
    UserRole.admin_sistema, UserRole.direccion, UserRole.servicios_escolares,
    UserRole.coordinador_academico, UserRole.tesoreria,
)


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
    from app.services.roles import access_of

    public = UserPublic.model_validate(user, from_attributes=True)
    if is_all_campus(user):
        public.campuses = await _all_campus_ids(session)
        public.all_campuses = True
    else:
        public.campuses = await _member_campus_ids(session, user)
        public.all_campuses = False
    permissions, own, role_name = await access_of(session, user)
    public.permissions = sorted(permissions)
    public.own_subjects_only = own
    public.role_name = role_name
    return public


# The campuses this request's user may act on, whatever the header shows: the
# header is a view filter, not a permission. None = every campus.
_UNSET = object()
_access: ContextVar[object] = ContextVar("campus_access", default=_UNSET)


async def active_campus(
    request: Request, session: SessionDep, current_user: CurrentUser
) -> list[uuid.UUID] | None:
    """Resolve the request's campus scope from the X-Campus header.

    Returns None (unrestricted) for all-campus users and for the "all view";
    otherwise the list of campus ids the query/write must be confined to. A
    specific X-Campus id is 403 unless the user is all-campus or a member."""
    header = request.headers.get("X-Campus")
    all_campus = is_all_campus(current_user)
    _access.set(None if all_campus else await _member_campus_ids(session, current_user))
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
    """Guard a create/update: raise 403 when the target campus is one the user
    can't act on. The campus chosen in the header only filters what is shown: an
    administrator viewing «Campus A» can still create a RVOE in campus B, and a
    member can act on any campus they belong to."""
    access = _access.get()
    if access is not _UNSET:
        scope = access  # type: ignore[assignment]
    if scope is not None and campus_id not in scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a ese plantel"
        )
