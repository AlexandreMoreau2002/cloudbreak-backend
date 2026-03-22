"""
Seed initial — sommets français et alpins pour la mer de nuage.

Les données sont dans app/db/peaks_data.json (généré via Overpass API / OSM).
Pour régénérer : python scripts/generate_peaks.py

Usage :
    python -m app.db.seed

Prérequis :
    docker compose -f ../infra/docker-compose.dev.yml up -d
    alembic upgrade head
"""

import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import text

from app.models.peak import Peak
from app.db.session import async_session_maker, engine

logger = logging.getLogger(__name__)

PEAKS_FILE = Path(__file__).parent / "peaks_data.json"


def load_peaks() -> list[dict[str, object]]:
    with PEAKS_FILE.open(encoding="utf-8") as f:
        data: list[dict[str, object]] = json.load(f)
        return data


async def seed() -> None:
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM peaks"))
        count = result.scalar()
        if count and count > 0:
            logger.warning(
                "seed_skipped",
                extra={"reason": "non vide", "count": count, "hint": "DELETE FROM peaks"},
            )
            return

        peaks_data = load_peaks()
        for data in peaks_data:
            peak = Peak(**data)
            session.add(peak)

        await session.commit()
        logger.info("seed_completed", extra={"count": len(peaks_data)})


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
