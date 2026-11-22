"""Roles (Administración → Roles): which views each role may open, and new roles.
The server reads these permissions on every request (deps.require_view)."""
import re
import unicodedata
import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CanRoles, CanRolesRead, SessionDep
from app.core.permissions import ADMIN_ROLE, ALL_PERMISSIONS, SPECIAL, VIEWS
from app.models import Role, RoleCreate, RolePermission, RolePublic, RoleUpdate, User
from app.services import audit

router = APIRouter(prefix="/roles", tags=["roles"])


def _code_for(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:48] or "rol"


async def _public(session, role: Role) -> RolePublic:
    permissions = sorted(
        (await session.exec(select(RolePermission.permission).where(RolePermission.role_id == role.id))).all()
    )
    if role.code == ADMIN_ROLE:
        permissions = sorted(ALL_PERMISSIONS)  # always everything
    users = (await session.exec(select(func.count()).select_from(User).where(User.role == role.code))).one()
    return RolePublic(**role.model_dump(), permissions=permissions, users_count=users)


async def _set_permissions(session, role: Role, permissions: list[str]) -> None:
    unknown = set(permissions) - ALL_PERMISSIONS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Permiso desconocido: {', '.join(sorted(unknown))}")
    for row in (await session.exec(select(RolePermission).where(RolePermission.role_id == role.id))).all():
        await session.delete(row)
    await session.flush()
    for permission in sorted(set(permissions)):
        session.add(RolePermission(role_id=role.id, permission=permission))


@router.get("/permissions")
async def list_permissions(_: CanRolesRead) -> list[dict]:
    """The catalog: one entry per view (and special action), grouped by section."""
    return [{"code": c, "label": label, "section": section} for c, label, section in VIEWS + SPECIAL]


@router.get("")
async def list_roles(session: SessionDep, _: CanRolesRead) -> list[RolePublic]:
    roles = (await session.exec(select(Role).order_by(Role.is_system.desc(), Role.name))).all()  # type: ignore[attr-defined]
    return [await _public(session, r) for r in roles]


@router.post("", status_code=201)
async def create_role(session: SessionDep, current_user: CanRoles, body: RoleCreate) -> RolePublic:
    code = _code_for(body.name)
    base, n = code, 2
    while (await session.exec(select(Role).where(Role.code == code))).first() or code == "alumno":
        code, n = f"{base}_{n}", n + 1
    role = Role(code=code, name=body.name.strip(), description=body.description.strip(),
                own_subjects_only=body.own_subjects_only)
    session.add(role)
    await session.flush()
    await _set_permissions(session, role, body.permissions)
    audit.record(session, actor=current_user.email, action="role.created", entity="role",
                 entity_id=str(role.id), detail=f"{role.name}: {', '.join(sorted(body.permissions))}")
    await session.commit()
    await session.refresh(role)
    return await _public(session, role)


@router.patch("/{role_id}")
async def update_role(
    session: SessionDep, current_user: CanRoles, role_id: uuid.UUID, body: RoleUpdate
) -> RolePublic:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    changes = body.model_dump(exclude_unset=True)
    if role.code == ADMIN_ROLE and (
        changes.get("permissions") is not None or changes.get("is_active") is False
        or changes.get("own_subjects_only")
    ):
        raise HTTPException(status_code=409, detail="El administrador de sistema siempre tiene todos los permisos")
    if role.code == current_user.role and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="No puedes desactivar tu propio rol")
    for key in ("name", "description"):
        if changes.get(key) is not None:
            setattr(role, key, changes[key].strip())
    for key in ("own_subjects_only", "is_active"):
        if changes.get(key) is not None:
            setattr(role, key, changes[key])
    session.add(role)
    if changes.get("permissions") is not None:
        before = set((await session.exec(
            select(RolePermission.permission).where(RolePermission.role_id == role.id))).all())
        await _set_permissions(session, role, changes["permissions"])
        after = set(changes["permissions"])
        detail = "; ".join(filter(None, [
            ("+ " + ", ".join(sorted(after - before))) if after - before else "",
            ("- " + ", ".join(sorted(before - after))) if before - after else "",
        ])) or "sin cambios de permisos"
    else:
        detail = ", ".join(sorted(changes))
    audit.record(session, actor=current_user.email, action="role.updated", entity="role",
                 entity_id=str(role.id), detail=f"{role.name}: {detail}")
    await session.commit()
    await session.refresh(role)
    return await _public(session, role)


@router.delete("/{role_id}", status_code=204)
async def delete_role(session: SessionDep, current_user: CanRoles, role_id: uuid.UUID) -> None:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if role.is_system:
        raise HTTPException(status_code=409, detail="Los roles del sistema no se borran; se pueden desactivar")
    if (await session.exec(select(User.id).where(User.role == role.code))).first():
        raise HTTPException(status_code=409, detail="Hay usuarios con este rol: cámbiales el rol antes de borrarlo")
    for row in (await session.exec(select(RolePermission).where(RolePermission.role_id == role.id))).all():
        await session.delete(row)
    await session.delete(role)
    audit.record(session, actor=current_user.email, action="role.deleted", entity="role",
                 entity_id=str(role_id), detail=role.name)
    await session.commit()
