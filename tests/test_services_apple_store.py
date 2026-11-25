from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.apple_store import (
    AppleSignedDataVerifier,
    AppleStoreBundleError,
    AppleStoreEnvironmentError,
    AppleStoreProductError,
    AppleStoreRevokedError,
    AppleStoreTransactionError,
)
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.NotificationTypeV2 import NotificationTypeV2
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
    VerificationStatus,
)

MONTHLY_PRODUCT_ID = "com.alexandremoreau.cloudbreak.premium.monthly"
ANNUAL_PRODUCT_ID = "com.alexandremoreau.cloudbreak.premium.annual"


class FakeSignedDataVerifier:
    def __init__(self, payload: object | Exception) -> None:
        self.payload = payload

    def verify_and_decode_signed_transaction(self, _: str) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def verify_and_decode_notification(self, _: str) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def payload(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "transaction_id": "123",
        "original_transaction_id": "456",
        "bundle_id": "com.alexandremoreau.cloudbreak",
        "product_id": MONTHLY_PRODUCT_ID,
        "app_account_token": "123e4567-e89b-12d3-a456-426614174000",
        "expires_date": int((datetime.now(UTC) + timedelta(days=7)).timestamp() * 1000),
        "revocation_date": None,
        "environment": "Sandbox",
        "offer_type": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def verifier(decoded_payload: object | Exception) -> AppleSignedDataVerifier:
    return AppleSignedDataVerifier(
        bundle_id="com.alexandremoreau.cloudbreak",
        environment="Sandbox",
        app_apple_id=None,
        allowed_product_ids=(MONTHLY_PRODUCT_ID, ANNUAL_PRODUCT_ID),
        signed_data_verifier=FakeSignedDataVerifier(decoded_payload),
    )


def test_verify_transaction_maps_introductory_offer_to_trial() -> None:
    transaction = verifier(payload(offer_type=1)).verify_transaction("valid-jws" * 3)

    assert transaction.status == "trial"
    assert transaction.product_id == MONTHLY_PRODUCT_ID
    assert transaction.app_account_token == UUID("123e4567-e89b-12d3-a456-426614174000")


def test_verify_transaction_maps_paid_entitlement_to_active() -> None:
    transaction = verifier(payload(offer_type=None)).verify_transaction("valid-jws" * 3)

    assert transaction.status == "active"


def test_verify_transaction_rejects_unlisted_product() -> None:
    with pytest.raises(AppleStoreProductError):
        verifier(payload(product_id="com.example.unlisted")).verify_transaction("valid-jws" * 3)


def test_verify_transaction_rejects_bad_bundle() -> None:
    with pytest.raises(AppleStoreBundleError):
        verifier(payload(bundle_id="com.example.other")).verify_transaction("valid-jws" * 3)


def test_verify_transaction_rejects_mismatched_environment() -> None:
    with pytest.raises(AppleStoreEnvironmentError):
        verifier(payload(environment="Production")).verify_transaction("valid-jws" * 3)


def test_verify_transaction_rejects_revoked_entitlement() -> None:
    with pytest.raises(AppleStoreRevokedError):
        transaction_verifier = verifier(
            payload(revocation_date=int(datetime.now(UTC).timestamp() * 1000))
        )
        transaction_verifier.verify_transaction("valid-jws" * 3)


def test_verify_transaction_rejects_expired_entitlement() -> None:
    expired = int((datetime.now(UTC) - timedelta(seconds=1)).timestamp() * 1000)

    with pytest.raises(AppleStoreTransactionError, match="expired"):
        verifier(payload(expires_date=expired)).verify_transaction("valid-jws" * 3)


def test_verify_transaction_maps_inactive_lifecycle_event_when_explicitly_allowed() -> None:
    revoked_at = int(datetime.now(UTC).timestamp() * 1000)

    transaction = verifier(payload(revocation_date=revoked_at)).verify_transaction(
        "valid-jws" * 3,
        allow_inactive=True,
    )

    assert transaction.status == "revoked"
    assert transaction.revoked_at == datetime.fromtimestamp(revoked_at / 1000, tz=UTC)


def test_verify_transaction_wraps_malformed_jws() -> None:
    with pytest.raises(AppleStoreTransactionError, match="signature"):
        verifier(ValueError("invalid signature")).verify_transaction("malformed-jws" * 2)


def test_verify_notification_normalizes_library_notification_type_enum() -> None:
    decoded_notification = SimpleNamespace(
        notificationType=NotificationTypeV2.DID_RENEW,
        notificationUUID="notification-123",
        signedDate=int(datetime.now(UTC).timestamp() * 1000),
        data=SimpleNamespace(signedTransactionInfo="transaction-jws"),
    )

    notification = verifier(decoded_notification).verify_notification("notification-jws")

    assert notification.notification_type == "DID_RENEW"


def wrong_environment() -> VerificationException:
    return VerificationException(VerificationStatus.INVALID_ENVIRONMENT)


def production_verifier(
    production_result: object | Exception,
    sandbox_result: object | Exception,
) -> AppleSignedDataVerifier:
    return AppleSignedDataVerifier(
        bundle_id="com.alexandremoreau.cloudbreak",
        environment="Production",
        app_apple_id=123456789,
        allowed_product_ids=(MONTHLY_PRODUCT_ID, ANNUAL_PRODUCT_ID),
        signed_data_verifier=FakeSignedDataVerifier(production_result),
        sandbox_signed_data_verifier=FakeSignedDataVerifier(sandbox_result),
    )


def test_production_accepts_sandbox_transaction_and_marks_environment() -> None:
    transaction = production_verifier(wrong_environment(), payload()).verify_transaction("jws" * 5)

    assert transaction.environment == "Sandbox"
    assert transaction.status == "trial"


def test_production_accepts_production_transaction_without_sandbox_fallback() -> None:
    transaction = production_verifier(
        payload(environment="Production"),
        AssertionError("sandbox verifier must not be used"),
    ).verify_transaction("jws" * 5)

    assert transaction.environment == "Production"


def test_production_rejects_invalid_signature_without_sandbox_fallback() -> None:
    with pytest.raises(AppleStoreTransactionError, match="signature"):
        production_verifier(
            VerificationException(VerificationStatus.VERIFICATION_FAILURE),
            payload(),
        ).verify_transaction("jws" * 5)


def test_production_rejects_wrong_bundle_without_sandbox_fallback() -> None:
    with pytest.raises(AppleStoreTransactionError):
        production_verifier(
            VerificationException(VerificationStatus.INVALID_APP_IDENTIFIER),
            payload(),
        ).verify_transaction("jws" * 5)


def test_production_rejects_sandbox_jws_invalid_for_sandbox_too() -> None:
    with pytest.raises(AppleStoreTransactionError, match="signature"):
        production_verifier(
            wrong_environment(),
            VerificationException(VerificationStatus.VERIFICATION_FAILURE),
        ).verify_transaction("jws" * 5)


def test_production_still_rejects_bad_bundle_and_product_on_sandbox_transaction() -> None:
    with pytest.raises(AppleStoreBundleError):
        production_verifier(
            wrong_environment(), payload(bundle_id="com.example.other")
        ).verify_transaction("jws" * 5)
    with pytest.raises(AppleStoreProductError):
        production_verifier(
            wrong_environment(), payload(product_id="com.example.unlisted")
        ).verify_transaction("jws" * 5)


def test_production_rejects_sandbox_verifier_returning_other_environment() -> None:
    with pytest.raises(AppleStoreEnvironmentError):
        production_verifier(
            wrong_environment(), payload(environment="Production")
        ).verify_transaction("jws" * 5)


def test_sandbox_environment_does_not_accept_production_transaction() -> None:
    with pytest.raises(AppleStoreTransactionError):
        verifier(wrong_environment()).verify_transaction("jws" * 5)


def test_sandbox_environment_accepts_sandbox_transaction() -> None:
    assert verifier(payload()).verify_transaction("jws" * 5).environment == "Sandbox"


def test_production_notifications_are_verified_for_production_only() -> None:
    with pytest.raises(AppleStoreTransactionError, match="notification"):
        production_verifier(wrong_environment(), payload()).verify_notification("jws" * 5)


def test_production_builds_real_sandbox_verifier_without_app_apple_id() -> None:
    production = AppleSignedDataVerifier(
        bundle_id="com.alexandremoreau.cloudbreak",
        environment="Production",
        app_apple_id=123456789,
        allowed_product_ids=(MONTHLY_PRODUCT_ID, ANNUAL_PRODUCT_ID),
    )

    assert isinstance(production._sandbox_signed_data_verifier, SignedDataVerifier)
    assert production._sandbox_signed_data_verifier._environment == Environment.SANDBOX
    assert production._sandbox_signed_data_verifier._app_apple_id is None


def test_sandbox_environment_has_no_sandbox_fallback_verifier() -> None:
    development = AppleSignedDataVerifier(
        bundle_id="com.alexandremoreau.cloudbreak",
        environment="Sandbox",
        app_apple_id=None,
        allowed_product_ids=(MONTHLY_PRODUCT_ID, ANNUAL_PRODUCT_ID),
    )

    assert development._sandbox_signed_data_verifier is None
