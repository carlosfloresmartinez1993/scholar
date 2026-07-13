"""Sequential folio counters (RF-D05): one row per institution+series,
incremented under row lock so folios are unique and gap-minimal."""
import uuid

from sqlmodel import Field, SQLModel, UniqueConstraint


class FolioCounter(SQLModel, table=True):
    __tablename__ = "folio_counters"
    __table_args__ = (UniqueConstraint("institution_id", "series", name="uq_folio_series"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    series: str = Field(max_length=16)  # e.g. "CON", "REC", "ACTA", "TIT"
    last_number: int = Field(default=0, ge=0)
