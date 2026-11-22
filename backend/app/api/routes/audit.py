from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import (
    CanAuditoria,
    SessionDep,
)
from app.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(session: SessionDep, _: CanAuditoria, limit: int = 200) -> list[AuditLog]:
    return (
        await session.exec(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    ).all()
