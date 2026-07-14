"""Folio issuance (RF-D05): unique, sequential, per institution and series."""
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.folio import FolioCounter

SERIES = {
    "constancia_estudios": "CON",
    "constancia_no_adeudo": "CNA",
    "carta_pasante": "CPA",
    "kardex": "KDX",
    "certificado_parcial": "CEP",
    "certificado_total": "CET",
    "acta": "ACT",
    "recibo": "REC",
    "titulo": "TIT",
    "diploma": "DIP",
    "grado": "GRA",
}


async def next_folio(session: AsyncSession, institution_id: uuid.UUID, series_key: str) -> str:
    """Returns e.g. 'CON-000042'. Atomic upsert on the counter row (safe under
    concurrency even before the row exists); caller's commit persists it."""
    series = SERIES.get(series_key, series_key[:3].upper())
    insert = sqlite_insert if session.bind.dialect.name == "sqlite" else pg_insert
    stmt = (
        insert(FolioCounter)
        .values(id=uuid.uuid4(), institution_id=institution_id, series=series, last_number=1)
        .on_conflict_do_update(
            index_elements=["institution_id", "series"],
            set_={"last_number": FolioCounter.__table__.c.last_number + 1},
        )
        .returning(FolioCounter.__table__.c.last_number)
    )
    number = (await session.execute(stmt)).scalar_one()
    return f"{series}-{number:06d}"
