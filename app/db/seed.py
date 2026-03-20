"""
Seed initial — sommets français connus pour la mer de nuage.

Usage :
    python -m app.db.seed

Prérequis :
    docker compose -f ../infra/docker-compose.dev.yml up -d
    alembic upgrade head
"""

import asyncio
import logging

from sqlalchemy import text

from app.db.session import async_session_maker, engine
from app.models.peak import Peak

logger = logging.getLogger(__name__)

PEAKS = [
    {
        "id": "11111111-0000-0000-0000-000000000001",
        "name": "Puy de Dôme",
        "slug": "puy-de-dome",
        "lat": 45.7725,
        "lng": 2.9656,
        "altitude": 1465,
    },
    {
        "id": "11111111-0000-0000-0000-000000000002",
        "name": "Mont Ventoux",
        "slug": "mont-ventoux",
        "lat": 44.1742,
        "lng": 5.2789,
        "altitude": 1912,
    },
    {
        "id": "11111111-0000-0000-0000-000000000003",
        "name": "Crêt de la Neige",
        "slug": "cret-de-la-neige",
        "lat": 46.3811,
        "lng": 5.6281,
        "altitude": 1720,
    },
    {
        "id": "11111111-0000-0000-0000-000000000004",
        "name": "Grand Ballon",
        "slug": "grand-ballon",
        "lat": 47.9004,
        "lng": 7.1005,
        "altitude": 1424,
    },
    {
        "id": "11111111-0000-0000-0000-000000000005",
        "name": "Ballon d'Alsace",
        "slug": "ballon-d-alsace",
        "lat": 47.8193,
        "lng": 6.8576,
        "altitude": 1247,
    },
    {
        "id": "11111111-0000-0000-0000-000000000006",
        "name": "Pic Saint-Loup",
        "slug": "pic-saint-loup",
        "lat": 43.7917,
        "lng": 3.7333,
        "altitude": 658,
    },
    {
        "id": "11111111-0000-0000-0000-000000000007",
        "name": "Mont Salève",
        "slug": "mont-saleve",
        "lat": 46.1339,
        "lng": 6.1633,
        "altitude": 1379,
    },
    {
        "id": "11111111-0000-0000-0000-000000000008",
        "name": "Roc'h Trevezel",
        "slug": "roch-trevezel",
        "lat": 48.3711,
        "lng": -3.9617,
        "altitude": 384,
    },
    {
        "id": "11111111-0000-0000-0000-000000000009",
        "name": "Pic du Midi de Bigorre",
        "slug": "pic-du-midi-de-bigorre",
        "lat": 42.9368,
        "lng": 0.1412,
        "altitude": 2877,
    },
    {
        "id": "11111111-0000-0000-0000-000000000010",
        "name": "Mont Aigoual",
        "slug": "mont-aigoual",
        "lat": 44.1211,
        "lng": 3.5831,
        "altitude": 1567,
    },
]


async def seed() -> None:
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM peaks"))
        count = result.scalar()
        if count and count > 0:
            logger.warning("seed_skipped", extra={"reason": "table peaks non vide", "count": count})
            print(f"⚠️  Table peaks contient déjà {count} entrée(s) — seed ignoré.")
            print("   Pour forcer : DELETE FROM peaks; puis relancer.")
            return

        for data in PEAKS:
            peak = Peak(**data)
            session.add(peak)

        await session.commit()
        print(f"✅ {len(PEAKS)} sommets insérés.")
        for p in PEAKS:
            print(f"   {p['name']:30s} {p['altitude']}m  id={p['id']}")


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
