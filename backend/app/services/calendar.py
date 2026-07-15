"""Thin async client for the calendar system (timetable-engine, calendar.inue.online).

The calendar is the source of truth for programs and scheduling; scholar links
its own rows (Program.calendar_program_id / Group.calendar_group_id) to
calendar ids and reads published schedules through this client. All calendar
endpoints live under /api/v1/integration and are authenticated with X-API-Key.
"""
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings

TIMEOUT_SECONDS = 10.0


async def _get(path: str, params: dict[str, str] | None = None) -> Any:
    if not settings.CALENDAR_API_URL:
        raise HTTPException(status_code=503, detail="Calendar integration not configured")
    url = f"{settings.CALENDAR_API_URL.rstrip('/')}/api/v1/integration{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                url, params=params, headers={"X-API-Key": settings.CALENDAR_API_KEY}
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="No se pudo contactar al sistema de calendario"
        ) from exc
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error del sistema de calendario ({response.status_code})",
        )
    return response.json()


async def get_campuses() -> list[dict]:
    return await _get("/campuses")


async def get_programs() -> list[dict]:
    return await _get("/programs")


async def get_groups(
    term_id: uuid.UUID | None = None, program_id: uuid.UUID | None = None
) -> list[dict]:
    params: dict[str, str] = {}
    if term_id:
        params["term_id"] = str(term_id)
    if program_id:
        params["program_id"] = str(program_id)
    return await _get("/groups", params or None)


async def get_schedule(
    group_id: uuid.UUID, term_id: uuid.UUID | None = None
) -> list[dict]:
    params: dict[str, str] = {"group_id": str(group_id)}
    if term_id:
        params["term_id"] = str(term_id)
    return await _get("/schedule", params)
