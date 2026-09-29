from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SubscriptionPlan = Literal["free", "premium"]
SubscriptionStatus = Literal["none", "trial", "active", "expired", "revoked"]


class SubscriptionVerifyRequest(BaseModel):
    """JWS transaction signed by Apple's StoreKit 2 service."""

    signed_transaction: str = Field(min_length=20, max_length=20_000)


class SubscriptionResponse(BaseModel):
    """Current subscription entitlement returned to the mobile client."""

    plan: SubscriptionPlan
    status: SubscriptionStatus
    expires_at: datetime | None
