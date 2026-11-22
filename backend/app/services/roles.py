"""Roles and their permissions: the defaults Scholar starts with, and what a user
may do (read on every request)."""
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.permissions import ADMIN_ROLE, ALL_PERMISSIONS, DEFAULT_ROLES
from app.models import Role, RolePermission, User


async def ensure_default_roles(session: AsyncSession) -> None:
    """Create the system roles that are missing (never touches edited ones)."""
    existing = set((await session.exec(select(Role.code))).all())
    for code, name, own, permissions in DEFAULT_ROLES:
        if code in existing:
            continue
        role = Role(code=code, name=name, is_system=True, own_subjects_only=own)
        session.add(role)
        await session.flush()
        for permission in sorted(permissions):
            session.add(RolePermission(role_id=role.id, permission=permission))
    await session.flush()


async def access_of(session: AsyncSession, user: User) -> tuple[set[str], bool, str]:
    """(permissions, own_subjects_only, role name) of a user. A superuser and the
    system administrator have everything; an inactive or unknown role, nothing."""
    role = (await session.exec(select(Role).where(Role.code == user.role))).first()
    if user.is_superuser or user.role == ADMIN_ROLE:
        return set(ALL_PERMISSIONS), False, role.name if role else "Administrador"
    if role is None or not role.is_active:
        return set(), False, role.name if role else str(user.role)
    permissions = set(
        (await session.exec(select(RolePermission.permission).where(RolePermission.role_id == role.id))).all()
    )
    return permissions & ALL_PERMISSIONS, role.own_subjects_only, role.name
