from uuid import uuid4
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.subscription import (
    SubscriptionOwnershipConflict,
    apply_apple_notification,
    apply_verified_transaction,
    get_subscription_response,
    is_entitlement_notification,
    record_apple_notification,
)
from app.models.subscription import Subscription
from app.models.apple_subscription_event import AppleSubscriptionEvent
from app.services.apple_store import VerifiedAppleNotification, VerifiedAppleTransaction


def _transaction(
    *,
    expires_at: datetime | None = None,
    original_transaction_id: str = "original-123",
    transaction_id: str = "transaction-123",
    revoked_at: datetime | None = None,
    status: str = "trial",
) -> VerifiedAppleTransaction:
    return VerifiedAppleTransaction(
        transaction_id=transaction_id,
        original_transaction_id=original_transaction_id,
        product_id="com.alexandremoreau.cloudbreak.premium.monthly",
        app_account_token=uuid4(),
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=30),
        revoked_at=revoked_at,
        environment="Sandbox",
        status=status,  # type: ignore[arg-type]
    )


def _notification(notification_type: str) -> VerifiedAppleNotification:
    return VerifiedAppleNotification(
        notification_uuid="notification-123",
        notification_type=notification_type,
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction="verified-transaction-jws",
        signed_renewal_info=None,
    )


@pytest.mark.asyncio
async def test_apply_verified_transaction_writes_premium_for_monthly_or_annual() -> None:
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, empty, empty, empty])
    db.flush = AsyncMock()

    monthly = await apply_verified_transaction("user-123", _transaction(), db)
    annual = await apply_verified_transaction(
        "user-456",
        _transaction(
            original_transaction_id="original-456",
            transaction_id="transaction-456",
        ),
        db,
    )

    assert monthly.plan == "premium"
    assert annual.plan == "premium"
    assert monthly.status == "trial"
    assert annual.status == "trial"


@pytest.mark.asyncio
async def test_apply_verified_transaction_is_idempotent_for_same_owner() -> None:
    stored = Subscription(
        user_id="user-123",
        plan="premium",
        status="active",
        original_transaction_id="original-123",
        latest_transaction_id="transaction-123",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    found = MagicMock()
    found.scalar_one_or_none.return_value = stored
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)
    db.flush = AsyncMock()

    result = await apply_verified_transaction("user-123", _transaction(), db)

    assert result is stored
    assert db.add.call_count == 0


@pytest.mark.asyncio
async def test_apply_verified_transaction_rejects_foreign_original_transaction() -> None:
    stored = Subscription(
        user_id="owner-123",
        plan="premium",
        original_transaction_id="original-123",
    )
    found = MagicMock()
    found.scalar_one_or_none.return_value = stored
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)
    db.flush = AsyncMock()

    with pytest.raises(SubscriptionOwnershipConflict):
        await apply_verified_transaction("attacker-456", _transaction(), db)


def _nested_transaction(db: MagicMock) -> None:
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested.return_value = nested


@pytest.mark.asyncio
async def test_apply_verified_transaction_rereads_same_owner_after_insert_race() -> None:
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    persisted = Subscription(
        user_id="user-123",
        plan="premium",
        status="trial",
        original_transaction_id="original-123",
        latest_transaction_id="transaction-123",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    reread = MagicMock()
    reread.scalar_one_or_none.return_value = persisted
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, empty, reread])
    db.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("duplicate original transaction"))
    )
    _nested_transaction(db)

    result = await apply_verified_transaction("user-123", _transaction(), db)

    assert result is persisted
    assert db.execute.await_count == 3
    db.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_apply_verified_transaction_rejects_foreign_owner_after_insert_race() -> None:
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    persisted = Subscription(
        user_id="owner-456",
        plan="premium",
        original_transaction_id="original-123",
    )
    reread = MagicMock()
    reread.scalar_one_or_none.return_value = persisted
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, empty, reread])
    db.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("duplicate original transaction"))
    )
    _nested_transaction(db)

    with pytest.raises(SubscriptionOwnershipConflict):
        await apply_verified_transaction("attacker-789", _transaction(), db)

    assert db.execute.await_count == 3
    db.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_apply_verified_transaction_keeps_newer_entitlement_over_older_restore() -> None:
    newer_expiry = datetime.now(UTC) + timedelta(days=60)
    stored = Subscription(
        user_id="user-123",
        plan="premium",
        status="active",
        original_transaction_id="original-123",
        latest_transaction_id="transaction-new",
        expires_at=newer_expiry,
    )
    found = MagicMock()
    found.scalar_one_or_none.return_value = stored
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)
    db.flush = AsyncMock()

    result = await apply_verified_transaction(
        "user-123",
        _transaction(expires_at=datetime.now(UTC) + timedelta(days=30)),
        db,
    )

    assert result is stored
    assert result.expires_at == newer_expiry
    assert result.latest_transaction_id == "transaction-new"


@pytest.mark.asyncio
async def test_get_subscription_response_returns_free_none_for_unknown_user() -> None:
    found = MagicMock()
    found.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)

    response = await get_subscription_response("missing-user", db)

    assert response.plan == "free"
    assert response.status == "none"
    assert response.expires_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("notification_type", "transaction_status"),
    [
        ("SUBSCRIBED", "trial"),
        ("DID_RENEW", "active"),
        ("EXPIRED", "expired"),
        ("REFUND", "revoked"),
        ("REVOKE", "revoked"),
        ("REFUND_REVERSED", "active"),
        ("RENEWAL_EXTENDED", "active"),
    ],
)
async def test_apply_apple_notification_projects_lifecycle_status(
    notification_type: str,
    transaction_status: str,
) -> None:
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, empty, empty])
    db.flush = AsyncMock()

    transaction = _transaction(
        expires_at=datetime.now(UTC) + timedelta(days=30),
        transaction_id=f"transaction-{notification_type}",
        revoked_at=datetime.now(UTC) if notification_type in {"REFUND", "REVOKE"} else None,
        status=transaction_status,
    )
    subscription = await apply_apple_notification(_notification(notification_type), transaction, db)

    assert subscription is not None
    assert subscription.plan == "premium"
    assert subscription.status == transaction_status
    if notification_type in {"REFUND", "REVOKE"}:
        assert subscription.expires_at == transaction.revoked_at
    assert any(isinstance(call.args[0], AppleSubscriptionEvent) for call in db.add.call_args_list)


@pytest.mark.asyncio
async def test_apply_apple_notification_is_a_no_op_for_duplicate_notification_uuid() -> None:
    event = AppleSubscriptionEvent(
        notification_uuid="notification-123",
        notification_type="DID_RENEW",
    )
    found = MagicMock()
    found.scalar_one_or_none.return_value = event
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)

    subscription = await apply_apple_notification(
        _notification("DID_RENEW"),
        _transaction(),
        db,
    )

    assert subscription is None
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_delayed_expired_notification_does_not_regress_newer_renewal() -> None:
    transaction = _transaction(
        expires_at=datetime.now(UTC) - timedelta(days=1),
        transaction_id="transaction-expired-old",
        status="expired",
    )
    subscription = Subscription(
        user_id=str(transaction.app_account_token),
        plan="premium",
        status="active",
        original_transaction_id="original-123",
        latest_transaction_id="transaction-renewed",
        expires_at=datetime.now(UTC) + timedelta(days=60),
    )
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    owner = MagicMock()
    owner.scalar_one_or_none.return_value = subscription
    newer_event = MagicMock()
    newer_event.scalar_one_or_none.return_value = datetime.now(UTC)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, owner, newer_event])
    db.flush = AsyncMock()
    delayed_notification = VerifiedAppleNotification(
        notification_uuid="notification-expired-old",
        notification_type="EXPIRED",
        subtype=None,
        signed_date=datetime.now(UTC) - timedelta(days=1),
        signed_transaction="expired-transaction-jws",
        signed_renewal_info=None,
    )

    result = await apply_apple_notification(
        delayed_notification,
        transaction,
        db,
    )

    assert result is subscription
    assert subscription.status == "active"
    assert subscription.latest_transaction_id == "transaction-renewed"
    assert any(isinstance(call.args[0], AppleSubscriptionEvent) for call in db.add.call_args_list)


@pytest.mark.asyncio
async def test_delayed_refund_notification_does_not_revoke_newer_renewal() -> None:
    transaction = _transaction(
        expires_at=datetime.now(UTC) + timedelta(days=30),
        transaction_id="transaction-refund-old",
        revoked_at=datetime.now(UTC) - timedelta(days=1),
        status="revoked",
    )
    subscription = Subscription(
        user_id=str(transaction.app_account_token),
        plan="premium",
        status="active",
        original_transaction_id="original-123",
        latest_transaction_id="transaction-renewed",
        expires_at=datetime.now(UTC) + timedelta(days=60),
    )
    original_expiry = subscription.expires_at
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    owner = MagicMock()
    owner.scalar_one_or_none.return_value = subscription
    newer_event = MagicMock()
    newer_event.scalar_one_or_none.return_value = datetime.now(UTC) - timedelta(days=2)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, owner, newer_event])
    db.flush = AsyncMock()
    delayed_notification = VerifiedAppleNotification(
        notification_uuid="notification-refund-old",
        notification_type="REFUND",
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction="refund-transaction-jws",
        signed_renewal_info=None,
    )

    result = await apply_apple_notification(delayed_notification, transaction, db)

    assert result is subscription
    assert subscription.status == "active"
    assert subscription.expires_at == original_expiry
    assert subscription.latest_transaction_id == "transaction-renewed"
    assert any(isinstance(call.args[0], AppleSubscriptionEvent) for call in db.add.call_args_list)


@pytest.mark.asyncio
async def test_refund_for_current_transaction_revokes_subscription() -> None:
    transaction = _transaction(
        transaction_id="transaction-current",
        revoked_at=datetime.now(UTC),
        status="revoked",
    )
    subscription = Subscription(
        user_id=str(transaction.app_account_token),
        plan="premium",
        status="active",
        original_transaction_id=transaction.original_transaction_id,
        latest_transaction_id=transaction.transaction_id,
        expires_at=transaction.expires_at,
    )
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    owner = MagicMock()
    owner.scalar_one_or_none.return_value = subscription
    newer_event = MagicMock()
    newer_event.scalar_one_or_none.return_value = datetime.now(UTC) - timedelta(days=1)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[empty, owner, newer_event])
    db.flush = AsyncMock()
    refund_notification = VerifiedAppleNotification(
        notification_uuid="notification-refund-current",
        notification_type="REFUND",
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction="current-refund-transaction-jws",
        signed_renewal_info=None,
    )

    result = await apply_apple_notification(refund_notification, transaction, db)

    assert result is subscription
    assert subscription.status == "revoked"
    assert subscription.expires_at == transaction.revoked_at
    assert subscription.latest_transaction_id == transaction.transaction_id
    assert any(isinstance(call.args[0], AppleSubscriptionEvent) for call in db.add.call_args_list)


@pytest.mark.asyncio
async def test_record_apple_notification_keeps_irrelevant_verified_event_as_no_op() -> None:
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=empty)
    db.flush = AsyncMock()
    notification = VerifiedAppleNotification(
        notification_uuid="notification-test-123",
        notification_type="TEST",
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction=None,
        signed_renewal_info=None,
    )

    created = await record_apple_notification(notification, db)

    assert created is True
    assert isinstance(db.add.call_args.args[0], AppleSubscriptionEvent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "notification_type",
    ["DID_CHANGE_RENEWAL_PREF", "DID_FAIL_TO_RENEW", "GRACE_PERIOD_EXPIRED"],
)
async def test_non_entitlement_lifecycle_events_are_ledger_only(notification_type: str) -> None:
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=empty)
    db.flush = AsyncMock()
    existing_subscription = Subscription(
        user_id="user-123",
        plan="premium",
        status="active",
        original_transaction_id="original-123",
        latest_transaction_id="monthly-transaction-123",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    subscription_state = (
        existing_subscription.plan,
        existing_subscription.status,
        existing_subscription.expires_at,
        existing_subscription.latest_transaction_id,
    )

    assert is_entitlement_notification(notification_type) is False
    created = await record_apple_notification(_notification(notification_type), db)

    assert created is True
    assert isinstance(db.add.call_args.args[0], AppleSubscriptionEvent)
    assert not any(isinstance(call.args[0], Subscription) for call in db.add.call_args_list)
    if notification_type == "DID_CHANGE_RENEWAL_PREF":
        assert (
            existing_subscription.plan,
            existing_subscription.status,
            existing_subscription.expires_at,
            existing_subscription.latest_transaction_id,
        ) == subscription_state
