"""
Injecte les viewpoints urbains manquants dans la DB sans vider la table.

Usage :
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python scripts/add_missing_peaks.py
"""

import asyncio
import re
import uuid
import unicodedata
import logging

from sqlalchemy import select

from app.db.session import async_session_maker, engine
from app.models.peak import Peak

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

MISSING: list[dict] = [
    {"name": "La Bastille", "lat": 45.1947, "lng": 5.7230, "altitude": 476},
    {"name": "Colline de Fourvière", "lat": 45.7613, "lng": 4.8221, "altitude": 295},
    {"name": "Mont Saint-Clair", "lat": 43.3993, "lng": 3.6988, "altitude": 176},
    {"name": "Butte Montmartre", "lat": 48.8867, "lng": 2.3431, "altitude": 130},
    {"name": "Colline du Château", "lat": 43.6963, "lng": 7.2767, "altitude": 92},
]


def slugify(name: str) -> str:
    name = name.replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_str.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-")


def make_id(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudbreak:peak:{slug}"))


async def main() -> None:
    async with async_session_maker() as session:
        for entry in MISSING:
            slug = slugify(entry["name"])
            peak_id = make_id(slug)

            existing = await session.execute(select(Peak).where(Peak.slug == slug))
            if existing.scalar_one_or_none():
                logger.info("  ⏭  déjà présent : %s", slug)
                continue

            peak = Peak(
                id=peak_id,
                name=entry["name"],
                slug=slug,
                lat=entry["lat"],
                lng=entry["lng"],
                altitude=entry["altitude"],
            )
            session.add(peak)
            logger.info("  ✅ ajouté : %s (%dm)", entry["name"], entry["altitude"])

        await session.commit()
        logger.info("\nTerminé.")


async def run() -> None:
    await main()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
