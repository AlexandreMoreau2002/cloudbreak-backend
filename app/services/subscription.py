"""Persistence rules for current Apple subscription entitlements and lifecycle events."""

from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.apple_subscription_event import AppleSubscriptionEvent
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionPlan, SubscriptionResponse, SubscriptionStatus
from app.services.apple_store import VerifiedAppleNotification, VerifiedAppleTransaction


class SubscriptionOwnershipConflict(Exception):
    """An Apple subscription lineage is already bound to another account."""


class AppleNotificationInvalid(Exception):
    """A cryptographically verified notification lacks safe entitlement data."""


async def _get_transaction_owner(
    original_transaction_id: str,
    db: AsyncSession,
) -> Subscription | None:
    result = await db.execute(
        select(Subscription)
        .where(Subscription.original_transaction_id == original_transaction_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _get_processed_event(
    notification_uuid: str,
    db: AsyncSession,
) -> AppleSubscriptionEvent | None:
    result = await db.execute(
        select(AppleSubscriptionEvent)
        .where(AppleSubscriptionEvent.notification_uuid == notification_uuid)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_subscription_response(user_id: str, db: AsyncSession) -> SubscriptionResponse:
    """Return a safe, free entitlement when no current subscription exists."""
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    subscription = result.scalar_one_or_none()
    if subscription is None:
        return SubscriptionResponse(plan="free", status="none", expires_at=None)

    plan: SubscriptionPlan = "premium" if subscription.plan in {"premium", "pro"} else "free"
    known_statuses = {"trial", "active", "expired", "revoked"}
    stored_status = cast(str | None, subscription.status)
    status: SubscriptionStatus = (
        cast(SubscriptionStatus, stored_status) if stored_status in known_statuses else "none"
    )
    return SubscriptionResponse(
        plan=plan,
        status=status,
        expires_at=cast(datetime | None, subscription.expires_at),
    )


async def apply_verified_transaction(
    user_id: str,
    transaction: VerifiedAppleTransaction,
    db: AsyncSession,
) -> Subscription:
    """Bind a verified Apple entitlement to exactly one Cloudbreak account."""
    subscription = await _get_transaction_owner(transaction.original_transaction_id, db)

    if subscription is not None and subscription.user_id != user_id:
        raise SubscriptionOwnershipConflict()

    if subscription is None:
        user_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id).with_for_update()
        )
        subscription = user_result.scalar_one_or_none()

    created = subscription is None
    if subscription is None:
        subscription = Subscription(user_id=user_id)

    if subscription.original_transaction_id not in (None, transaction.original_transaction_id):
        raise SubscriptionOwnershipConflict()

    stored_expiry = subscription.expires_at
    if stored_expiry is not None and stored_expiry > transaction.expires_at:
        return subscription

    try:
        async with db.begin_nested():
            if created:
                db.add(subscription)
            subscription_values = cast(Any, subscription)
            subscription_values.plan = "premium"
            subscription_values.status = transaction.status
            subscription_values.expires_at = transaction.expires_at
            subscription_values.original_transaction_id = transaction.original_transaction_id
            subscription_values.latest_transaction_id = transaction.transaction_id
            subscription_values.apple_environment = transaction.environment
            await db.flush()
    except IntegrityError:
        subscription = await _get_transaction_owner(transaction.original_transaction_id, db)
        if subscription is None or subscription.user_id != user_id:
            raise SubscriptionOwnershipConflict() from None
    return subscription


_NOTIFICATION_STATUSES: dict[str, Literal["trial", "active", "expired", "revoked"] | None] = {
    "SUBSCRIBED": None,
    "DID_RENEW": None,
    "EXPIRED": "expired",
    "REFUND": "revoked",
}


async def apply_apple_notification(
    notification: VerifiedAppleNotification,
    transaction: VerifiedAppleTransaction,
    db: AsyncSession,
) -> Subscription | None:
    """Atomically record one Apple lifecycle event and update its owned entitlement.

    The caller must have verified the outer notification JWS and the nested transaction JWS.
    Duplicate notification UUIDs are explicitly harmless.
    """
    if not notification.notification_uuid:
        raise AppleNotificationInvalid("Apple notification UUID is missing")

    if await _get_processed_event(notification.notification_uuid, db) is not None:
        return None

    if notification.notification_type not in _NOTIFICATION_STATUSES:
        raise AppleNotificationInvalid("Unsupported Apple notification type")
    target_status = _NOTIFICATION_STATUSES[notification.notification_type] or transaction.status

    subscription = await _get_transaction_owner(transaction.original_transaction_id, db)
    if subscription is None:
        if transaction.app_account_token is None:
            raise AppleNotificationInvalid("Apple notification account token is missing")
        user_id = str(transaction.app_account_token)
        user_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id).with_for_update()
        )
        subscription = user_result.scalar_one_or_none()
    else:
        user_id = str(subscription.user_id)

    if transaction.app_account_token is not None and str(transaction.app_account_token) != user_id:
        raise SubscriptionOwnershipConflict()

    created = subscription is None
    if subscription is None:
        subscription = Subscription(user_id=user_id)

    if target_status == "revoked":
        if transaction.revoked_at is None:
            raise AppleNotificationInvalid("Refund notification has no revocation date")
        effective_expiry = transaction.revoked_at
    else:
        effective_expiry = transaction.expires_at

    event = AppleSubscriptionEvent(
        notification_uuid=notification.notification_uuid,
        notification_type=notification.notification_type,
        original_transaction_id=transaction.original_transaction_id,
        signed_date=notification.signed_date,
    )
    try:
        async with db.begin_nested():
            db.add(event)
            if created:
                db.add(subscription)
            subscription_values = cast(Any, subscription)
            subscription_values.plan = "premium"
            subscription_values.status = target_status
            subscription_values.expires_at = effective_expiry
            subscription_values.original_transaction_id = transaction.original_transaction_id
            subscription_values.latest_transaction_id = transaction.transaction_id
            subscription_values.apple_environment = transaction.environment
            await db.flush()
    except IntegrityError:
        if await _get_processed_event(notification.notification_uuid, db) is not None:
            return None
        raise
    return subscription
