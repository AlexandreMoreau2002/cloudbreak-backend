from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.subscription import SubscriptionResponse, SubscriptionVerifyRequest


def test_subscription_verify_rejects_blank_signed_transaction() -> None:
    with pytest.raises(ValidationError):
        SubscriptionVerifyRequest(signed_transaction="")


def test_subscription_verify_accepts_jws_shaped_transaction() -> None:
    request = SubscriptionVerifyRequest(signed_transaction="a" * 20)

    assert request.signed_transaction == "a" * 20


@pytest.mark.parametrize("expires_at", [datetime(2026, 1, 2, tzinfo=UTC), None])
def test_subscription_response_serializes_expiration(expires_at: datetime | None) -> None:
    response = SubscriptionResponse(plan="premium", status="active", expires_at=expires_at)

    assert response.model_dump(mode="json")["expires_at"] == (
        "2026-01-02T00:00:00Z" if expires_at else None
    )
