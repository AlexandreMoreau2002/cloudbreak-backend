"""
Seed initial — sommets français et alpins pour la mer de nuage.

Les données sont dans app/db/peaks_data.json.
Régénération réseau complète : python scripts/generate_peaks.py
Enrichissement local du champ region : python scripts/enrich_region.py

Usage :
    python -m app.db.seed

Prérequis :
    docker compose -f ../infra/docker-compose.dev.yml up -d
    alembic upgrade head
"""

import json
import asyncio
import logging
from pathlib import Path
from app.models.peak import Peak
from sqlalchemy.dialects.postgresql import insert
from app.db.session import async_session_maker, engine

logger = logging.getLogger(__name__)

BATCH_SIZE = 1_000
PEAKS_FILE = Path(__file__).parent / "peaks_data.json"


def load_peaks() -> list[dict[str, object]]:
    with PEAKS_FILE.open(encoding="utf-8") as f:
        data: list[dict[str, object]] = json.load(f)
        return data


async def seed() -> None:
    async with async_session_maker() as session:
        peaks_data = load_peaks()

        for start in range(0, len(peaks_data), BATCH_SIZE):
            batch = peaks_data[start : start + BATCH_SIZE]
            stmt = insert(Peak).values(batch)
            upsert = stmt.on_conflict_do_update(
                index_elements=[Peak.slug],
                set_={
                    "name": stmt.excluded.name,
                    "lat": stmt.excluded.lat,
                    "lng": stmt.excluded.lng,
                    "altitude": stmt.excluded.altitude,
                    "region": stmt.excluded.region,
                },
            )
            await session.execute(upsert)

        await session.commit()
        logger.info(
            "seed_completed",
            extra={
                "count": len(peaks_data),
                "mode": "upsert_on_slug",
                "batch_size": BATCH_SIZE,
            },
        )


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
