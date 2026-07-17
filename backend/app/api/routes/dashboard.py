"""Inicio dashboard: per-level counts + cartera vencida (term-over-term) and
period-scoped metrics/series/activity over a 1/7/14/30-day window."""
from fastapi import APIRouter, HTTPException

from app.api.deps import AnyStaff, SessionDep
from app.services.dashboard import (
    VALID_PERIOD_DAYS,
    dashboard_stats,
    enrollments_series,
    recent_activity,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _check_days(days: int) -> None:
    if days not in VALID_PERIOD_DAYS:
        raise HTTPException(status_code=422, detail="days debe ser 1, 7, 14 o 30")


@router.get("/stats")
async def stats(session: SessionDep, _: AnyStaff, days: int = 30) -> dict:
    _check_days(days)
    return await dashboard_stats(session, days=days)


@router.get("/enrollments-series")
async def get_enrollments_series(
    session: SessionDep, _: AnyStaff, days: int = 30
) -> list[dict]:
    """New group-enrollments per day for the selected period."""
    _check_days(days)
    return await enrollments_series(session, days)


@router.get("/activity")
async def activity(
    session: SessionDep, _: AnyStaff, days: int = 30, limit: int = 10
) -> list[dict]:
    """Recent audit entries for the dashboard (same guard as the rest of the
    dashboard; the full /audit view stays superuser-only)."""
    _check_days(days)
    entries = await recent_activity(session, days, limit)
    return [e.model_dump(mode="json") for e in entries]
