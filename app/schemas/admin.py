from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.subscription import SubscriptionPlan, SubscriptionStatus


class HeartbeatRequest(BaseModel):
    status: Literal["ok", "fail"]
    duration_s: float | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=200)


class ServerMetricsRequest(BaseModel):
    sampled_at: datetime
    cpu_load_1m: float = Field(ge=0)
    cpu_count: int = Field(ge=0)
    mem_total_mb: float = Field(ge=0)
    mem_available_mb: float = Field(ge=0)
    swap_total_mb: float = Field(ge=0)
    swap_used_mb: float = Field(ge=0)
    disk_total_gb: float = Field(ge=0)
    disk_used_gb: float = Field(ge=0)


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserLookupRequest(BaseModel):
    """Recherche exacte : un email complet, jamais un fragment."""

    email: str = Field(min_length=5, max_length=320, pattern=EMAIL_PATTERN)


class GrantPremiumRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    days: int = Field(ge=1, le=366)


class AdminUserSubscription(BaseModel):
    """Compte trouvé : jamais l'email, uniquement l'identifiant et l'entitlement."""

    user_id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    expires_at: datetime | None
    origin: Literal["apple", "granted"] | None
    premium_active: bool
