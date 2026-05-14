import logging
from typing import Any
from sqlalchemy import select
from redis.asyncio import Redis
from app.db.session import get_db
from datetime import UTC, datetime
from app.core.config import settings
from app.core.errors import ErrorCode
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.subscription import Subscription
from app.core.security import decode_supabase_jwt
from fastapi import Depends, HTTPException, Request, status
from app.services.quota import QuotaService, QuotaExceededException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()

# Redis singleton
_redis: Redis | None = None


async def get_redis() -> Redis:
    """Retourne le client Redis (singleton)."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, object]:
    """Valide JWT Supabase et retourne l'utilisateur actuel."""
    token = credentials.credentials
    try:
        payload = decode_supabase_jwt(token, settings.supabase_jwt_jwks)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"id": user_id, "email": payload.get("email")}


async def get_user_subscription(user_id: str, db: AsyncSession) -> Subscription | None:
    """
    Récupère la souscription active d'un utilisateur (Premium/Pro).

    Args:
        user_id: ID utilisateur Supabase
        db: Session DB

    Returns:
        Record Subscription ou None si absent
    """
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    subscription = result.scalar_one_or_none()
    logger.debug(
        "subscription_lookup",
        extra={
            "user_id": user_id,
            "plan": subscription.plan if subscription else None,
        },
    )
    return subscription


async def check_quota(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Vérifie le quota quotidien Redis pour les utilisateurs freemium.

    Premium/Pro bypass automatiquement.
    Freemium : max 1 check/jour, reset minuit UTC.

    Args:
        user: Utilisateur actuel (JWT validé)
        redis: Client Redis
        db: Session DB

    Returns:
        user si OK

    Raises:
        HTTPException(429) si quota dépassé
    """
    user_id = user["id"]

    # Vérifier si Premium/Pro
    subscription = await get_user_subscription(user_id, db)
    if (
        subscription
        and subscription.plan in ("premium", "pro")
        and subscription.expires_at is not None
        and subscription.expires_at > datetime.now(subscription.expires_at.tzinfo)
    ):
        logger.debug(
            "quota_bypassed",
            extra={
                "user_id": user_id,
                "plan": subscription.plan,
            },
        )
        return user

    # Freemium : vérifier le quota
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    quota_service = QuotaService(redis)

    peak_id = request.query_params.get("peak_id", "")
    if not peak_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"detail": "peak_id requis", "code": "VALIDATION_ERROR"},
        )

    try:
        await quota_service.check_and_increment(user_id, today, peak_id)
    except QuotaExceededException:
        logger.warning(
            "quota_exceeded",
            extra={
                "user_id": user_id,
                "date": today,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "Quota journalier atteint",
                "code": ErrorCode.QUOTA_EXCEEDED,
            },
        ) from None

    return user
