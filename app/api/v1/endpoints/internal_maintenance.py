"""Jobs internes de maintenance, déclenchés par un cron (jamais par l'app mobile)."""

import logging
from dataclasses import asdict

from redis.asyncio import Redis
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode
from app.core.dependencies import get_redis, require_cron_secret
from app.services.anonymous_purge import purge_inactive_anonymous_accounts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/maintenance", tags=["internal"])


@router.post("/purge-anonymous", dependencies=[Depends(require_cron_secret)])
async def purge_anonymous(
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, int | bool]:
    """Purge les comptes anonymes inactifs (compteurs seulement, jamais d'identifiant)."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("anonymous_purge_supabase_not_configured")
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API Admin Supabase non configurée",
            ErrorCode.SERVICE_UNAVAILABLE,
        )
    summary = await purge_inactive_anonymous_accounts(
        db,
        redis,
        retention_days=settings.anon_retention_days,
        max_per_run=settings.anon_purge_max_per_run,
        dry_run=dry_run,
        supabase_url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
    )
    return asdict(summary)
