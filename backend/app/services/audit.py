from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog


def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Adds an audit row to the session; caller commits."""
    session.add(
        AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, detail=detail)
    )
