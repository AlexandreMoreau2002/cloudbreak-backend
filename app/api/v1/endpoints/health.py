import logging
from sqlalchemy import text
from redis.asyncio import Redis
from app.db.session import get_db
from fastapi import APIRouter, Depends
from app.core.dependencies import get_redis
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, object]:
    services: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        services["database"] = "ok"
    except Exception as exc:
        logger.error("health_db_failed", extra={"error": str(exc)})
        services["database"] = "unavailable"

    try:
        await redis.ping()
        services["redis"] = "ok"
    except Exception as exc:
        logger.error("health_redis_failed", extra={"error": str(exc)})
        services["redis"] = "unavailable"

    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "services": services}
