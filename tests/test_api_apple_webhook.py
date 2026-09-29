"""Public App Store Server Notifications V2 route tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1.endpoints.subscription import get_apple_signed_data_verifier
from app.db.session import get_db
from app.main import app
from app.services.apple_store import (
    AppleStoreTransactionError,
    VerifiedAppleNotification,
    VerifiedAppleTransaction,
)


def _notification() -> VerifiedAppleNotification:
    return VerifiedAppleNotification(
        notification_uuid="notification-123",
        notification_type="DID_RENEW",
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction="verified-transaction-jws",
        signed_renewal_info=None,
    )


def _transaction() -> VerifiedAppleTransaction:
    return VerifiedAppleTransaction(
        transaction_id="transaction-123",
        original_transaction_id="original-123",
        product_id="com.alexandremoreau.cloudbreak.premium.monthly",
        app_account_token=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=None,
        environment="Sandbox",
        status="active",
    )


def test_apple_webhook_verifies_before_any_database_mutation() -> None:
    verifier = MagicMock()
    verifier.verify_notification.side_effect = AppleStoreTransactionError("invalid")
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/webhooks/apple",
                json={"signedPayload": "invalid-notification-payload"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


def test_apple_webhook_projects_verified_notification_and_returns_no_content() -> None:
    verifier = MagicMock()
    verifier.verify_notification.return_value = _notification()
    verifier.verify_transaction.return_value = _transaction()
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    with patch(
        "app.api.v1.endpoints.subscription.apply_apple_notification",
        new_callable=AsyncMock,
    ):
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/webhooks/apple",
                    json={"signedPayload": "signed-apple-notification"},
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 204
    verifier.verify_notification.assert_called_once_with("signed-apple-notification")
    verifier.verify_transaction.assert_called_once_with(
        "verified-transaction-jws",
        allow_inactive=True,
    )
    db.commit.assert_awaited_once()
