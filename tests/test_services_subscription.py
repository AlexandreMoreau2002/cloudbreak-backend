from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.subscription import Subscription
from app.services.apple_store import VerifiedAppleTransaction
from app.services.subscription import (
    SubscriptionOwnershipConflict,
    apply_verified_transaction,
    get_subscription_response,
)


def _transaction(
    *,
    expires_at: datetime | None = None,
    original_transaction_id: str = "original-123",
    transaction_id: str = "transaction-123",
) -> VerifiedAppleTransaction:
    return VerifiedAppleTransaction(
        transaction_id=transaction_id,
        original_transaction_id=original_transaction_id,
        product_id="com.alexandremoreau.cloudbreak.premium.monthly",
        app_account_token=uuid4(),
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=30),
        revoked_at=None,
        environment="Sandbox",
        status="trial",
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
