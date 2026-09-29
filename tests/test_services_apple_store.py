from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.apple_store import (
    AppleStoreBundleError,
    AppleSignedDataVerifier,
    AppleStoreEnvironmentError,
    AppleStoreProductError,
    AppleStoreRevokedError,
    AppleStoreTransactionError,
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
        transaction_verifier.verify_transaction(
            "valid-jws" * 3
        )


def test_verify_transaction_rejects_expired_entitlement() -> None:
    expired = int((datetime.now(UTC) - timedelta(seconds=1)).timestamp() * 1000)

    with pytest.raises(AppleStoreTransactionError, match="expired"):
        verifier(payload(expires_date=expired)).verify_transaction("valid-jws" * 3)


def test_verify_transaction_wraps_malformed_jws() -> None:
    with pytest.raises(AppleStoreTransactionError, match="signature"):
        verifier(ValueError("invalid signature")).verify_transaction("malformed-jws" * 2)
