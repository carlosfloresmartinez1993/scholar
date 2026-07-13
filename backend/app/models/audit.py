import uuid
from datetime import datetime

from app.models.common import utcnow

from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor: str = Field(max_length=255)  # user email or "professor:<name>" or "system"
    action: str = Field(index=True, max_length=64)  # e.g. "publication.created", "invite.responded"
    entity: str | None = Field(default=None, max_length=64)
    entity_id: str | None = Field(default=None, max_length=64)
    detail: str | None = None
    created_at: datetime = Field(
        default_factory=utcnow, index=True
    )
