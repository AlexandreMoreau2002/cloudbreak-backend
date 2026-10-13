"""Jobs internes de notifications, déclenchés par un cron (jamais par l'app mobile)."""

import logging
from dataclasses import asdict

from redis.asyncio import Redis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.v1.endpoints.score import weather_service
from app.services.favorite_alerts import run_favorite_alerts
from app.core.dependencies import get_redis, require_cron_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/notifications", tags=["internal"])


@router.post("/run-favorites", dependencies=[Depends(require_cron_secret)])
async def run_favorites(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, int]:
    """Envoie les alertes « conditions idéales demain » aux Premium (appelé par le cron)."""
    summary = await run_favorite_alerts(db, redis, weather_service)
    return asdict(summary)
