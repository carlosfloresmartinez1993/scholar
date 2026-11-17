"""Planteles de un RVOE: el principal (rvoes.campus_id) y los demás donde se
imparte el mismo RVOE (rvoe_campuses). Same plan everywhere; each group belongs
to one of them, and a student to the campus of their group."""
import uuid

from fastapi import HTTPException
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Campus, Group, PlanVersion, Rvoe, RvoeCampus


async def campus_ids_of(session: AsyncSession, rvoe: Rvoe) -> list[uuid.UUID]:
    """Main campus first, then the others."""
    extra = (
        await session.exec(select(RvoeCampus.campus_id).where(RvoeCampus.rvoe_id == rvoe.id))
    ).all()
    return [rvoe.campus_id] + [c for c in extra if c != rvoe.campus_id]


async def campus_map(session: AsyncSession, rvoes: list[Rvoe]) -> dict[uuid.UUID, list[uuid.UUID]]:
    result = {r.id: [r.campus_id] for r in rvoes}
    if rvoes:
        for rvoe_id, campus_id in (
            await session.exec(
                select(RvoeCampus.rvoe_id, RvoeCampus.campus_id).where(
                    RvoeCampus.rvoe_id.in_(list(result))  # type: ignore[attr-defined]
                )
            )
        ).all():
            if campus_id not in result[rvoe_id]:
                result[rvoe_id].append(campus_id)
    return result


def offered_in(campus_ids):
    """SQL condition: the RVOE applies in one of these campuses."""
    return or_(
        Rvoe.campus_id.in_(campus_ids),  # type: ignore[attr-defined]
        Rvoe.id.in_(select(RvoeCampus.rvoe_id).where(RvoeCampus.campus_id.in_(campus_ids))),  # type: ignore[attr-defined]
    )


async def set_extra_campuses(session: AsyncSession, rvoe: Rvoe, extra_ids: list) -> None:
    """Replace the other planteles of an RVOE. A plantel that already has groups
    of this RVOE can't be taken away. Caller commits."""
    wanted = {uuid.UUID(str(c)) for c in extra_ids} - {rvoe.campus_id}
    for campus_id in wanted:
        if await session.get(Campus, campus_id) is None:
            raise HTTPException(status_code=404, detail="Plantel no encontrado")
    current = {
        row.campus_id: row
        for row in (await session.exec(select(RvoeCampus).where(RvoeCampus.rvoe_id == rvoe.id))).all()
    }
    for campus_id, row in current.items():
        if campus_id in wanted:
            continue
        in_use = (
            await session.exec(
                select(Group.id)
                .join(PlanVersion, PlanVersion.id == Group.plan_version_id)
                .where(PlanVersion.rvoe_id == rvoe.id, Group.campus_id == campus_id)
            )
        ).first()
        if in_use:
            campus = await session.get(Campus, campus_id)
            raise HTTPException(
                status_code=409,
                detail=f"{campus.name if campus else 'Ese plantel'} ya tiene grupos de este RVOE: no se puede quitar",
            )
        await session.delete(row)
    for campus_id in wanted - set(current):
        session.add(RvoeCampus(rvoe_id=rvoe.id, campus_id=campus_id))
    await session.flush()


async def group_campus(session: AsyncSession, rvoe: Rvoe, requested) -> uuid.UUID:
    """The campus a new group of this RVOE goes to: the one asked for, if the RVOE
    is offered there; by default the main one."""
    if requested is None:
        return rvoe.campus_id
    requested = uuid.UUID(str(requested))
    if requested not in await campus_ids_of(session, rvoe):
        raise HTTPException(status_code=422, detail="El RVOE de ese plan no se imparte en ese plantel")
    return requested
