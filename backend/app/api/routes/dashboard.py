"""Inicio dashboard stats (per-level counts + cartera vencida, term-over-term)."""
from fastapi import APIRouter

from app.api.deps import AnyStaff, SessionDep
from app.services.dashboard import dashboard_stats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def stats(session: SessionDep, _: AnyStaff) -> dict:
    return await dashboard_stats(session)
