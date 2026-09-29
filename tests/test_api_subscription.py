from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.v1.endpoints.subscription import get_apple_signed_data_verifier
from app.core.dependencies import get_current_user, get_permanent_user
from app.db.session import get_db
from app.main import app
from app.schemas.subscription import SubscriptionResponse
from app.services.apple_store import AppleStoreTransactionError, VerifiedAppleTransaction
from app.services.apple_store import (
    AppleStoreBundleError,
    AppleStoreEnvironmentError,
    AppleStoreProductError,
)
from app.services.subscription import SubscriptionOwnershipConflict


async def _override_db():
    yield AsyncMock()


def _transaction(*, app_account_token: object | None = None) -> VerifiedAppleTransaction:
    return VerifiedAppleTransaction(
        transaction_id="transaction-123",
        original_transaction_id="original-123",
        product_id="com.alexandremoreau.cloudbreak.premium.monthly",
        app_account_token=app_account_token or uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        revoked_at=None,
        environment="Sandbox",
        status="trial",
    )


def test_get_subscription_returns_free_response() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-123", "is_anonymous": False}
    app.dependency_overrides[get_db] = _override_db
    with patch(
        "app.api.v1.endpoints.subscription.get_subscription_response",
        new_callable=AsyncMock,
        return_value=SubscriptionResponse(plan="free", status="none", expires_at=None),
    ):
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/user/subscription")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"plan": "free", "status": "none", "expires_at": None}


def test_verify_persists_valid_transaction_for_permanent_account() -> None:
    user_id = str(uuid4())
    verifier = MagicMock()
    verifier.verify_transaction.return_value = _transaction(app_account_token=UUID(user_id))
    app.dependency_overrides[get_permanent_user] = lambda: {"id": user_id, "is_anonymous": False}
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    persisted = MagicMock()
    persisted.plan = "premium"
    persisted.status = "trial"
    persisted.expires_at = datetime.now(UTC) + timedelta(days=7)
    with patch(
        "app.api.v1.endpoints.subscription.apply_verified_transaction",
        new_callable=AsyncMock,
        return_value=persisted,
    ):
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/user/subscription/verify",
                    json={"signed_transaction": "not-a-real-jws-but-long-enough"},
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["plan"] == "premium"
    assert response.json()["status"] == "trial"
    assert response.json()["expires_at"].endswith("Z")


def test_verify_rejects_anonymous_account() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "anon-123", "is_anonymous": True}
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/user/subscription/verify",
                json={"signed_transaction": "not-a-real-jws-but-long-enough"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_REQUIRED"


def test_verify_requires_jwt() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/user/subscription/verify",
            json={"signed_transaction": "not-a-real-jws-but-long-enough"},
        )

    assert response.status_code == 403


def test_verify_maps_invalid_signed_transaction() -> None:
    verifier = MagicMock()
    verifier.verify_transaction.side_effect = AppleStoreTransactionError("invalid")
    app.dependency_overrides[get_permanent_user] = lambda: {
        "id": str(uuid4()),
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/user/subscription/verify",
                json={"signed_transaction": "not-a-real-jws-but-long-enough"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == "APPLE_TRANSACTION_INVALID"


@pytest.mark.parametrize(
    "verification_error",
    [
        AppleStoreProductError("unlisted product"),
        AppleStoreBundleError("wrong bundle"),
        AppleStoreEnvironmentError("wrong environment"),
    ],
)
def test_verify_maps_unsupported_apple_transaction(verification_error: Exception) -> None:
    verifier = MagicMock()
    verifier.verify_transaction.side_effect = verification_error
    app.dependency_overrides[get_permanent_user] = lambda: {
        "id": str(uuid4()),
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/user/subscription/verify",
                json={"signed_transaction": "not-a-real-jws-but-long-enough"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == "APPLE_TRANSACTION_UNSUPPORTED"


def test_verify_rejects_account_token_mismatch() -> None:
    verifier = MagicMock()
    verifier.verify_transaction.return_value = _transaction(app_account_token=uuid4())
    app.dependency_overrides[get_permanent_user] = lambda: {
        "id": str(uuid4()),
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/user/subscription/verify",
                json={"signed_transaction": "not-a-real-jws-but-long-enough"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == "APPLE_TRANSACTION_INVALID"


def test_verify_maps_foreign_replay_to_conflict() -> None:
    user_id = str(uuid4())
    verifier = MagicMock()
    verifier.verify_transaction.return_value = _transaction(app_account_token=UUID(user_id))
    app.dependency_overrides[get_permanent_user] = lambda: {"id": user_id, "is_anonymous": False}
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_apple_signed_data_verifier] = lambda: verifier
    with patch(
        "app.api.v1.endpoints.subscription.apply_verified_transaction",
        new_callable=AsyncMock,
        side_effect=SubscriptionOwnershipConflict(),
    ):
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/user/subscription/verify",
                    json={"signed_transaction": "not-a-real-jws-but-long-enough"},
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["code"] == "SUBSCRIPTION_OWNERSHIP_CONFLICT"
