from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import _audit_admin_overview, get_redis, require_admin
from app.core.errors import ApiError, ErrorCode
from app.db.session import get_db
from app.schemas.admin import AdminUserSubscription, GrantPremiumRequest, UserLookupRequest
from app.services import admin_users
from app.services.admin_overview import build_overview

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview")
async def overview(
    user: dict[str, object] = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, object]:
    try:
        data = await build_overview(db, redis)
    except Exception:
        await db.rollback()
        await _audit_admin_overview(db, str(user["id"]), "error")
        raise
    await _audit_admin_overview(db, str(user["id"]), "success")
    return data


def _audit_disabled() -> ApiError:
    return ApiError(503, "Audit indisponible", ErrorCode.ADMIN_AUDIT_DISABLED)


def _not_found() -> ApiError:
    return ApiError(404, "Compte introuvable", ErrorCode.ADMIN_USER_NOT_FOUND)


@router.post("/users/lookup")
async def lookup_user(
    body: UserLookupRequest,
    user: dict[str, object] = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserSubscription:
    try:
        return await admin_users.lookup_user(db, str(user["id"]), body.email)
    except admin_users.AuditDisabled:
        raise _audit_disabled() from None
    except admin_users.UserNotFound:
        raise _not_found() from None


@router.post("/users/grant-premium")
async def grant_premium(
    body: GrantPremiumRequest,
    user: dict[str, object] = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserSubscription:
    if not settings.audit_hash_key:
        raise _audit_disabled()
    try:
        return await admin_users.grant_premium(db, str(user["id"]), body.user_id, body.days)
    except admin_users.UserNotFound:
        raise _not_found() from None
    except admin_users.AppleSubscriptionActive:
        raise ApiError(
            409,
            "Abonnement Apple actif",
            ErrorCode.ADMIN_APPLE_SUBSCRIPTION_ACTIVE,
        ) from None
