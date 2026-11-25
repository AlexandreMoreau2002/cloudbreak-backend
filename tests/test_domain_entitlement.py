"""Règle d'entitlement Premium : un abonnement n'ouvre l'accès que s'il est actif et non expiré."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entitlement import effective_plan, is_entitlement_active

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(seconds=1)


@pytest.mark.parametrize("plan", ["premium", "pro"])
@pytest.mark.parametrize("status", ["trial", "active"])
def test_active_or_trial_future_subscription_is_entitled(plan: str, status: str) -> None:
    assert is_entitlement_active(plan, status, FUTURE, NOW) is True
    assert effective_plan(plan, status, FUTURE, NOW) == "premium"


@pytest.mark.parametrize("status", ["none", "expired", "revoked", None, "unknown"])
def test_non_active_status_is_not_entitled(status: str | None) -> None:
    assert is_entitlement_active("premium", status, FUTURE, NOW) is False
    assert effective_plan("premium", status, FUTURE, NOW) == "free"


def test_expired_date_is_not_entitled_even_if_status_is_still_active() -> None:
    assert is_entitlement_active("premium", "active", PAST, NOW) is False
    assert is_entitlement_active("premium", "active", NOW, NOW) is False


def test_missing_expiry_is_not_entitled() -> None:
    assert is_entitlement_active("premium", "active", None, NOW) is False


@pytest.mark.parametrize("plan", ["free", None, "other"])
def test_free_or_unknown_plan_is_not_entitled(plan: str | None) -> None:
    assert is_entitlement_active(plan, "active", FUTURE, NOW) is False
    assert effective_plan(plan, "active", FUTURE, NOW) == "free"


def test_now_defaults_to_current_time() -> None:
    soon = datetime.now(UTC) + timedelta(hours=1)
    assert is_entitlement_active("premium", "active", soon) is True
    assert (
        is_entitlement_active("premium", "active", datetime.now(UTC) - timedelta(hours=1)) is False
    )
