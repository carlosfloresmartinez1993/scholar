"""Idempotent seed: first superuser + INUE institution and main campus.
Run as `python -m app.initial_data`."""
import asyncio
import logging

from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.security import get_password_hash
from app.models import Campus, Institution, User, UserRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    async with async_session_factory() as session:
        institution = (await session.exec(select(Institution))).first()
        if institution is None:
            institution = Institution(
                name="Instituto Universitario Ensenada",
                short_name="INUE",
            )
            session.add(institution)
            await session.flush()
            session.add(
                Campus(institution_id=institution.id, name="Campus Ensenada")
            )
            logger.info("institution + campus created")

        existing = (
            await session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER))
        ).first()
        if existing is None:
            session.add(
                User(
                    email=settings.FIRST_SUPERUSER,
                    full_name="Superusuario",
                    role=UserRole.admin_sistema,
                    is_superuser=True,
                    hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                )
            )
            logger.info("superuser created: %s", settings.FIRST_SUPERUSER)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
