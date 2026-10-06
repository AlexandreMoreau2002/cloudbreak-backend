import logging
from uuid import UUID
from typing import Any, cast
from hashlib import sha256
from datetime import UTC, datetime

from sqlalchemy import select
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.session import get_db
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode
from app.services.analytics import track
from app.models.subscription import Subscription
from app.core.security import decode_supabase_jwt
from app.domain.entitlement import is_entitlement_active
from app.services.quota import QuotaService, QuotaExceededException
from app.services.rate_limit import RateLimitService, RateLimitExceededException

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()

# Redis singleton
_redis: Redis | None = None


def _identifier_hash(identifier: object) -> str:
    """Retourne un digest journalisable sans exposer l'identifiant source."""
    return sha256(str(identifier).encode()).hexdigest()


def _parse_installation_uuid4(value: str | None) -> UUID:
    """Valide le signal d'installation anonyme attendu par l'API score."""
    try:
        installation_uuid = UUID(value) if value else None
    except (ValueError, AttributeError, TypeError):
        installation_uuid = None

    if installation_uuid is None or installation_uuid.version != 4:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "Identifiant d'installation invalide",
            ErrorCode.INSTALLATION_ID_INVALID,
        )
    return installation_uuid


def decode_user_payload(payload: dict[str, Any]) -> dict[str, object]:
    """Construit le contexte utilisateur métier depuis les claims Supabase validés."""
    app_metadata = payload.get("app_metadata")
    provider = "email"
    if isinstance(app_metadata, dict) and isinstance(app_metadata.get("provider"), str):
        provider = app_metadata["provider"]
    return {
        "id": payload["sub"],
        "email": payload.get("email"),
        "is_anonymous": payload.get("is_anonymous") is True,
        "auth_provider": provider,
    }


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
        payload = decode_supabase_jwt(token, settings.supabase_jwt_jwks, settings.supabase_url)
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
    return decode_user_payload(payload)


def get_permanent_user(
    user: dict[str, object] = Depends(get_current_user),
) -> dict[str, object]:
    """Refuse les actions réservées à un compte Supabase permanent."""
    if user.get("is_anonymous") is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "Compte requis", "code": ErrorCode.ACCOUNT_REQUIRED},
        )
    return user


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
            "user_hash": _identifier_hash(user_id),
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
    is_premium = subscription is not None and is_entitlement_active(
        cast(str | None, subscription.plan),
        cast(str | None, subscription.status),
        cast(datetime | None, subscription.expires_at),
    )
    if is_premium and subscription is not None:
        logger.debug(
            "quota_bypassed",
            extra={
                "user_hash": _identifier_hash(user_id),
                "plan": subscription.plan,
            },
        )
        track("quota_bypassed", user_id, {"plan": subscription.plan})
        user["plan"] = subscription.plan
        return user

    # Freemium : vérifier le quota
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    peak_id = request.query_params.get("peak_id", "")
    if not peak_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"detail": "peak_id requis", "code": "VALIDATION_ERROR"},
        )

    installation_hash: str | None = None
    if user.get("is_anonymous") is True:
        installation_uuid = _parse_installation_uuid4(
            request.headers.get("X-Cloudbreak-Installation-Id")
        )
        installation_hash = _identifier_hash(installation_uuid)
        if request.client is None:
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Adresse IP client indisponible",
                ErrorCode.CLIENT_IP_UNAVAILABLE,
            )
        client_ip = request.client.host
        try:
            await RateLimitService(redis).check_anonymous_score(client_ip)
        except RateLimitExceededException:
            logger.warning(
                "anonymous_score_rate_limited",
                extra={
                    "plan": "free",
                    "peak_id": peak_id,
                    "installation_hash": installation_hash,
                },
            )
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Trop de requêtes",
                ErrorCode.RATE_LIMIT_EXCEEDED,
            ) from None

    quota_service = QuotaService(redis)
    try:
        if installation_hash is not None:
            await quota_service.check_and_increment_installation(installation_hash, today, peak_id)
        await quota_service.check_and_increment(str(user_id), today, peak_id)
    except QuotaExceededException:
        logger.warning(
            "score_quota_exceeded",
            extra={
                "plan": "free",
                "peak_id": peak_id,
                "user_hash": _identifier_hash(user_id),
                "installation_hash": installation_hash,
            },
        )
        track("quota_exceeded", user_id, {"peak_id": peak_id, "plan": "free"})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "Quota journalier atteint",
                "code": ErrorCode.QUOTA_EXCEEDED,
            },
        ) from None

    user["plan"] = "free"
    return user
