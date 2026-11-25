"""Public App Store Server Notifications V2 route tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
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


def test_apple_webhook_projects_verified_revoke_notification() -> None:
    verifier = MagicMock()
    notification = VerifiedAppleNotification(
        notification_uuid="notification-revoke-123",
        notification_type="REVOKE",
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction="verified-revoke-transaction-jws",
        signed_renewal_info=None,
    )
    transaction = VerifiedAppleTransaction(
        transaction_id="transaction-revoke-123",
        original_transaction_id="original-123",
        product_id="com.alexandremoreau.cloudbreak.premium.monthly",
        app_account_token=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=datetime.now(UTC),
        environment="Sandbox",
        status="revoked",
    )
    verifier.verify_notification.return_value = notification
    verifier.verify_transaction.return_value = transaction
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    with patch(
        "app.api.v1.endpoints.subscription.apply_apple_notification",
        new_callable=AsyncMock,
    ) as apply_notification:
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/webhooks/apple",
                    json={"signedPayload": "signed-apple-revoke-notification"},
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 204
    verifier.verify_transaction.assert_called_once_with(
        "verified-revoke-transaction-jws",
        allow_inactive=True,
    )
    apply_notification.assert_awaited_once_with(notification, transaction, db)
    db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("notification_type", "signed_transaction"),
    [
        ("DID_CHANGE_RENEWAL_PREF", "verified-transaction-jws"),
        ("DID_FAIL_TO_RENEW", "verified-transaction-jws"),
        ("GRACE_PERIOD_EXPIRED", "verified-transaction-jws"),
        ("TEST", None),
    ],
)
def test_apple_webhook_acknowledges_policy_events_without_entitlement(
    notification_type: str,
    signed_transaction: str | None,
) -> None:
    verifier = MagicMock()
    notification = VerifiedAppleNotification(
        notification_uuid=f"notification-{notification_type}",
        notification_type=notification_type,
        subtype=None,
        signed_date=datetime.now(UTC),
        signed_transaction=signed_transaction,
        signed_renewal_info=None,
    )
    verifier.verify_notification.return_value = notification
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    with patch(
        "app.api.v1.endpoints.subscription.record_apple_notification",
        new_callable=AsyncMock,
    ) as record_notification:
        with patch(
            "app.api.v1.endpoints.subscription.apply_apple_notification",
            new_callable=AsyncMock,
        ) as apply_notification:
            try:
                with TestClient(app) as client:
                    response = client.post(
                        "/api/v1/webhooks/apple",
                        json={"signedPayload": "signed-apple-notification"},
                    )
            finally:
                app.dependency_overrides.clear()

    assert response.status_code == 204
    verifier.verify_transaction.assert_not_called()
    apply_notification.assert_not_awaited()
    record_notification.assert_awaited_once_with(notification, db)
    db.commit.assert_awaited_once()
