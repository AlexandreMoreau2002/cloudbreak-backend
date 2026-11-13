"""Règle d'entitlement Premium — fonction pure, sans I/O.

Un abonnement n'ouvre l'accès Premium que s'il est actif (`trial` ou `active`) ET non expiré.
Le champ `plan` seul ne suffit jamais : il reste `premium` après une expiration ou un
remboursement, seuls `status` et `expires_at` changent.
"""

from datetime import UTC, datetime
from typing import Literal

PREMIUM_PLANS = frozenset({"premium", "pro"})
ACTIVE_STATUSES = frozenset({"trial", "active"})


def is_entitlement_active(
    plan: str | None,
    status: str | None,
    expires_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Vrai si l'abonnement donne l'accès Premium à l'instant `now` (UTC par défaut)."""
    if plan not in PREMIUM_PLANS or status not in ACTIVE_STATUSES or expires_at is None:
        return False
    return expires_at > (now or datetime.now(UTC))


def effective_plan(
    plan: str | None,
    status: str | None,
    expires_at: datetime | None,
    now: datetime | None = None,
) -> Literal["premium", "free"]:
    """Plan réellement applicable : `premium` seulement si l'entitlement est actif."""
    return "premium" if is_entitlement_active(plan, status, expires_at, now) else "free"
