"""Egresados: the graduate registry and its dashboard — who finished, from which
plan, in which period, and whether the título was registered (RF-C09)."""
import uuid

from fastapi import APIRouter

from app.api.deps import AnyStaff, CampusScope, SessionDep, ensure_in_scope
from app.models.alumni import AlumniRow, AlumniStats
from app.services import alumni

router = APIRouter(prefix="/alumni", tags=["alumni"])


@router.get("")
async def list_alumni(
    session: SessionDep,
    _: AnyStaff,
    scope: CampusScope,
    q: str | None = None,
    term_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
    titulado: bool | None = None,
) -> list[AlumniRow]:
    if campus_id:
        ensure_in_scope(scope, campus_id)  # a ?campus_id outside membership is 403
    return await alumni.alumni_rows(
        session,
        scope=scope,
        campus_id=campus_id,
        term_id=term_id,
        program_id=program_id,
        titulado=titulado,
        q=q,
    )


@router.get("/stats")
async def alumni_dashboard(
    session: SessionDep,
    _: AnyStaff,
    scope: CampusScope,
    q: str | None = None,
    term_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    campus_id: uuid.UUID | None = None,
    titulado: bool | None = None,
) -> AlumniStats:
    """Same filters as the list, on purpose: the cards above the table have to
    describe the table below them, not the whole registry."""
    if campus_id:
        ensure_in_scope(scope, campus_id)
    rows = await alumni.alumni_rows(
        session,
        scope=scope,
        campus_id=campus_id,
        term_id=term_id,
        program_id=program_id,
        titulado=titulado,
        q=q,
    )
    return alumni.alumni_stats(rows)
