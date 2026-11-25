"""Recherche d'un compte par email et octroi Premium (console admin, v1).

L'email n'est jamais écrit dans l'audit ni dans les logs : seule son empreinte HMAC-SHA256
(clé `AUDIT_HASH_KEY`) est conservée. La recherche est exacte : ni liste, ni correspondance
partielle.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.entitlement import is_entitlement_active
from app.models.admin_audit_log import AdminAuditLog
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.admin import AdminUserSubscription


class UserNotFound(Exception):
    """Aucun compte ne correspond."""


class AppleSubscriptionActive(Exception):
    """Un abonnement Apple actif ne doit jamais être écrasé par un octroi."""


class AuditDisabled(Exception):
    """`AUDIT_HASH_KEY` absent : on refuse plutôt que d'agir sans audit sûr."""


def hash_email(email: str) -> str:
    """Empreinte HMAC-SHA256 de l'email normalisé (minuscules, sans espaces)."""
    key = settings.audit_hash_key
    if not key:
        raise AuditDisabled()
    normalized = email.strip().lower()
    return hmac.new(key.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def _audit(
    actor_id: str,
    action: str,
    result: str,
    *,
    target_hash: str | None = None,
    target_user_id: str | None = None,
    grant_days: int | None = None,
) -> AdminAuditLog:
    return AdminAuditLog(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        action=action,
        resource="user",
        result=result,
        target_hash=target_hash,
        target_user_id=target_user_id,
        grant_days=grant_days,
    )


def _view(user_id: str, subscription: Subscription | None) -> AdminUserSubscription:
    if subscription is None:
        return AdminUserSubscription(
            user_id=user_id,
            plan="free",
            status="none",
            expires_at=None,
            origin=None,
            premium_active=False,
        )
    status = cast(str | None, subscription.status)
    expires_at = cast(datetime | None, subscription.expires_at)
    active = is_entitlement_active(cast(str | None, subscription.plan), status, expires_at)
    known = status if status in {"trial", "active", "expired", "revoked"} else "none"
    origin = cast(str, subscription.origin or "apple")
    return AdminUserSubscription(
        user_id=user_id,
        plan="premium" if active else "free",
        status=cast(Any, known),
        expires_at=expires_at,
        origin=cast(Any, origin if origin in {"apple", "granted"} else "apple"),
        premium_active=active,
    )


async def lookup_user(db: AsyncSession, actor_id: str, email: str) -> AdminUserSubscription:
    """Cherche un compte par email exact ; écrit toujours une ligne d'audit `user.lookup`."""
    target_hash = hash_email(email)
    result = await db.execute(
        select(User.supabase_user_id).where(func.lower(User.email) == email.strip().lower())
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        db.add(_audit(actor_id, "user.lookup", "not_found", target_hash=target_hash))
        await db.commit()
        raise UserNotFound()
    subscription = await db.get(Subscription, user_id)
    db.add(
        _audit(
            actor_id,
            "user.lookup",
            "success",
            target_hash=target_hash,
            target_user_id=user_id,
        )
    )
    await db.commit()
    return _view(user_id, subscription)


async def grant_premium(
    db: AsyncSession, actor_id: str, user_id: str, days: int
) -> AdminUserSubscription:
    """Offre (ou prolonge) un Premium `granted` ; refuse si un abonnement Apple est actif."""
    if await db.get(User, user_id) is None:
        db.add(_audit(actor_id, "subscription.grant", "not_found", grant_days=days))
        await db.commit()
        raise UserNotFound()

    now = datetime.now(UTC)
    subscription = await db.get(Subscription, user_id, with_for_update=True)
    if subscription is not None and (subscription.origin or "apple") == "apple":
        if is_entitlement_active(
            cast(str | None, subscription.plan),
            cast(str | None, subscription.status),
            cast(datetime | None, subscription.expires_at),
            now,
        ):
            db.add(
                _audit(
                    actor_id,
                    "subscription.grant",
                    "conflict",
                    target_user_id=user_id,
                    grant_days=days,
                )
            )
            await db.commit()
            raise AppleSubscriptionActive()

    if subscription is None:
        subscription = Subscription(user_id=user_id)
        db.add(subscription)
    values = cast(Any, subscription)
    current_end = cast(datetime | None, subscription.expires_at)
    still_granted = subscription.origin == "granted" and is_entitlement_active(
        cast(str | None, subscription.plan), cast(str | None, subscription.status), current_end, now
    )
    start = current_end if still_granted and current_end is not None else now
    values.plan = "premium"
    values.status = "active"
    values.origin = "granted"
    values.expires_at = start + timedelta(days=days)
    db.add(
        _audit(
            actor_id,
            "subscription.grant",
            "success",
            target_user_id=user_id,
            grant_days=days,
        )
    )
    await db.commit()
    return _view(user_id, subscription)
