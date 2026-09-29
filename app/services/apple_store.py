"""Verified boundary around Apple's App Store Server Library.

The application never reads a JWS payload directly.  Apple's verifier first
checks its signature and the adapter then limits it to Cloudbreak products.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier


class AppleStoreVerificationError(Exception):
    """Base error for an Apple payload that must not grant an entitlement."""


class AppleStoreTransactionError(AppleStoreVerificationError):
    """The transaction cannot be verified or is no longer entitled."""


class AppleStoreProductError(AppleStoreVerificationError):
    """The transaction does not concern a configured Cloudbreak product."""


class AppleStoreBundleError(AppleStoreVerificationError):
    """The transaction was issued for another application bundle."""


class AppleStoreEnvironmentError(AppleStoreVerificationError):
    """The transaction was issued for another App Store environment."""


class AppleStoreRevokedError(AppleStoreVerificationError):
    """The transaction was revoked by Apple."""


class SignedDataDecoder(Protocol):
    def verify_and_decode_signed_transaction(self, signed_transaction: str) -> Any: ...

    def verify_and_decode_notification(self, signed_payload: str) -> Any: ...


@dataclass(frozen=True)
class VerifiedAppleTransaction:
    transaction_id: str
    original_transaction_id: str
    product_id: str
    app_account_token: UUID | None
    expires_at: datetime
    revoked_at: datetime | None
    environment: str
    status: Literal["trial", "active", "expired", "revoked"]


@dataclass(frozen=True)
class VerifiedAppleNotification:
    notification_type: str
    subtype: str | None
    notification_uuid: str
    signed_date: datetime | None
    signed_transaction: str | None
    signed_renewal_info: str | None


@lru_cache(maxsize=1)
def apple_root_certificates() -> list[bytes]:
    """Load public Apple trust anchors once for the process lifetime."""
    resource_directory = Path(__file__).parents[1] / "resources/apple"
    certificate_names = (
        "AppleIncRootCertificate.cer",
        "AppleRootCA-G2.cer",
        "AppleRootCA-G3.cer",
    )
    return [
        (resource_directory / certificate_name).read_bytes()
        for certificate_name in certificate_names
    ]


class AppleSignedDataVerifier:
    """Application-owned, testable adapter over Apple's signed data verifier."""

    def __init__(
        self,
        *,
        bundle_id: str,
        environment: str,
        app_apple_id: int | None,
        allowed_product_ids: tuple[str, str],
        signed_data_verifier: SignedDataDecoder | None = None,
    ) -> None:
        if environment not in (Environment.SANDBOX.value, Environment.PRODUCTION.value):
            raise ValueError(f"Unsupported Apple environment: {environment}")
        if environment == Environment.PRODUCTION.value and app_apple_id is None:
            raise ValueError("Production Apple verification requires an app Apple ID")

        self._bundle_id = bundle_id
        self._environment = environment
        self._allowed_product_ids = allowed_product_ids
        self._signed_data_verifier = signed_data_verifier or SignedDataVerifier(
            apple_root_certificates(),
            True,
            Environment(environment),
            bundle_id,
            app_apple_id,
        )

    def verify_transaction(
        self,
        signed_transaction: str,
        *,
        allow_inactive: bool = False,
    ) -> VerifiedAppleTransaction:
        """Verify a StoreKit JWS and return a configured Cloudbreak entitlement."""
        try:
            payload = self._signed_data_verifier.verify_and_decode_signed_transaction(
                signed_transaction
            )
        except Exception as error:
            raise AppleStoreTransactionError("Apple transaction signature is invalid") from error

        bundle_id = self._value(payload, "bundleId", "bundle_id")
        if bundle_id != self._bundle_id:
            raise AppleStoreBundleError("Apple transaction bundle does not match Cloudbreak")

        environment = self._enum_value(self._value(payload, "environment"))
        if environment != self._environment:
            raise AppleStoreEnvironmentError("Apple transaction environment does not match")

        product_id = self._value(payload, "productId", "product_id")
        if product_id not in self._allowed_product_ids:
            raise AppleStoreProductError("Apple transaction product is not configured")

        expires_at = self._timestamp(self._value(payload, "expiresDate", "expires_date"))
        if expires_at is None:
            raise AppleStoreTransactionError("Apple subscription transaction has no expiration")

        revoked_at = self._timestamp(self._value(payload, "revocationDate", "revocation_date"))
        if revoked_at is not None and not allow_inactive:
            raise AppleStoreRevokedError("Apple transaction has been revoked")
        if expires_at <= datetime.now(UTC) and not allow_inactive:
            raise AppleStoreTransactionError("Apple transaction is expired")

        transaction_id = self._value(payload, "transactionId", "transaction_id")
        original_transaction_id = self._value(
            payload, "originalTransactionId", "original_transaction_id"
        )
        if not transaction_id or not original_transaction_id:
            raise AppleStoreTransactionError("Apple transaction identifiers are missing")

        offer_type = self._enum_value(self._value(payload, "offerType", "offer_type"))
        transaction_status: Literal["trial", "active", "expired", "revoked"]
        if revoked_at is not None:
            transaction_status = "revoked"
        elif expires_at <= datetime.now(UTC):
            transaction_status = "expired"
        elif offer_type == 1:
            transaction_status = "trial"
        else:
            transaction_status = "active"
        return VerifiedAppleTransaction(
            transaction_id=str(transaction_id),
            original_transaction_id=str(original_transaction_id),
            product_id=str(product_id),
            app_account_token=self._uuid(
                self._value(payload, "appAccountToken", "app_account_token")
            ),
            expires_at=expires_at,
            revoked_at=revoked_at,
            environment=environment,
            status=transaction_status,
        )

    def verify_notification(self, signed_payload: str) -> VerifiedAppleNotification:
        """Verify an App Store Server Notification V2 without trusting its JWS body."""
        try:
            payload = self._signed_data_verifier.verify_and_decode_notification(signed_payload)
        except Exception as error:
            raise AppleStoreTransactionError("Apple notification signature is invalid") from error

        data = self._value(payload, "data")
        return VerifiedAppleNotification(
            notification_type=str(self._value(payload, "notificationType") or ""),
            subtype=self._optional_string(self._value(payload, "subtype")),
            notification_uuid=str(self._value(payload, "notificationUUID") or ""),
            signed_date=self._timestamp(self._value(payload, "signedDate")),
            signed_transaction=self._optional_string(
                self._value(data, "signedTransactionInfo") if data else None
            ),
            signed_renewal_info=self._optional_string(
                self._value(data, "signedRenewalInfo") if data else None
            ),
        )

    @staticmethod
    def _value(payload: object, *names: str) -> Any:
        for name in names:
            value = getattr(payload, name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _enum_value(value: object) -> Any:
        return getattr(value, "value", value)

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if value is None:
            return None
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)

    @staticmethod
    def _uuid(value: object) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(str(value))
        except ValueError as error:
            message = "Apple transaction account token is invalid"
            raise AppleStoreTransactionError(message) from error

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return str(value) if value is not None else None
