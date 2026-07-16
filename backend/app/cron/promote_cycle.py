"""Railway cron entrypoint for cycle promotion. Schedule this daily:

    python -m app.cron.promote_cycle

It promotes passing, continuing students into their linked next-term groups and
bills reinscripción PROMOTION_LEAD_DAYS before each term starts. Idempotent, so a
daily run is safe — already-promoted students are skipped."""
import asyncio
import logging

from sqlmodel import select

from app.core.db import async_session_factory
from app.models import User
from app.services.promotion import promote_cycle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    async with async_session_factory() as session:
        # charges need a real created_by user id → act as the first superuser
        actor = (
            await session.exec(select(User).where(User.is_superuser == True))  # noqa: E712
        ).first()
        if actor is None:
            logger.warning("cycle promotion: no superuser to act as; skipping")
            return
        result = await promote_cycle(session, actor, dry_run=False)
        logger.info(
            "cycle promotion: %s promoted, %s skipped",
            result["promoted_count"], result["skipped_count"],
        )


if __name__ == "__main__":
    asyncio.run(main())
