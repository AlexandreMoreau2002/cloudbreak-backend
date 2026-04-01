import logging
from typing import Any
from datetime import datetime
import redis.asyncio as aioredis
from app.db.session import get_db
from app.core.config import settings
from app.core.errors import ErrorCode
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import decode_supabase_jwt
from fastapi import Depends, HTTPException, status
from app.services.quota import QuotaService, QuotaExceededException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()

# Redis singleton
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Retourne le client Redis (singleton)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=False)  # type: ignore[no-untyped-call]
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


async def get_user_subscription(user_id: str, db: AsyncSession) -> Any:
    """
    Récupère la souscription d'un utilisateur (Premium/Pro).

    Implémenté en story 4.3 pour créer la table Subscription.
    Pour MVP 4.1 : retourne None (tout le monde freemium).

    Args:
        user_id: ID utilisateur Supabase
        db: Session DB

    Returns:
        Record Subscription ou None si absent/expiré
    """
    # TODO: Implémenté en story 4.3
    # Pour MVP 4.1, on retourne None (tout le monde freemium)
    return None


async def check_quota(
    user: dict[str, Any] = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
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
    if subscription and subscription.plan in ("premium", "pro"):
        # Vérifier que l'abonnement n'est pas expiré
        if subscription.expires_at > datetime.utcnow():
            logger.debug(
                "quota_bypassed",
                extra={
                    "user_id": user_id,
                    "plan": subscription.plan,
                },
            )
            return user

    # Freemium : vérifier le quota
    today = datetime.utcnow().strftime("%Y-%m-%d")
    quota_service = QuotaService(redis)

    try:
        await quota_service.check_and_increment(user_id, today)
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
