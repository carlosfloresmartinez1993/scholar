"""Niveles educativos: catálogo editable por institución (preescolar a doctorado,
o los que la escuela ofrezca). A program stores the level's code."""
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import DEFAULT_EDUCATION_LEVELS, EducationLevel


async def ensure_default_levels(session: AsyncSession, institution_id) -> None:
    """A new institution starts with the usual levels (it can rename, reorder or
    deactivate them). Does nothing once it has any. Caller commits."""
    existing = (
        await session.exec(select(EducationLevel.id).where(EducationLevel.institution_id == institution_id))
    ).first()
    if existing is not None:
        return
    for code, name, order in DEFAULT_EDUCATION_LEVELS:
        session.add(EducationLevel(institution_id=institution_id, code=code, name=name, sort_order=order))
    await session.flush()


async def levels_of(session: AsyncSession, institution_id, *, active_only: bool = False) -> list[EducationLevel]:
    query = select(EducationLevel).where(EducationLevel.institution_id == institution_id)
    if active_only:
        query = query.where(EducationLevel.is_active == True)  # noqa: E712
    return (await session.exec(query.order_by(EducationLevel.sort_order, EducationLevel.name))).all()


async def require_level(session: AsyncSession, institution_id, code: str) -> EducationLevel:
    level = (
        await session.exec(
            select(EducationLevel).where(
                EducationLevel.institution_id == institution_id, EducationLevel.code == code
            )
        )
    ).first()
    if level is None or not level.is_active:
        raise HTTPException(status_code=422, detail=f"El nivel «{code}» no existe o está inactivo")
    return level
