"""Folio issuance (RF-D05): unique, sequential, per institution and series."""
import uuid

from sqlmodel import select
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
    """Returns e.g. 'CON-000042'. Locks the counter row; caller's commit persists it."""
    series = SERIES.get(series_key, series_key[:3].upper())
    result = await session.exec(
        select(FolioCounter)
        .where(FolioCounter.institution_id == institution_id, FolioCounter.series == series)
        .with_for_update()
    )
    counter = result.first()
    if counter is None:
        counter = FolioCounter(institution_id=institution_id, series=series, last_number=0)
    counter.last_number += 1
    session.add(counter)
    return f"{series}-{counter.last_number:06d}"
