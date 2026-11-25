"""Tests des règles pures des alertes favoris."""

import pytest
from datetime import UTC, datetime

from app.domain.favorite_alerts import (
    ALERT_HOUR,
    resolve_locale,
    is_alert_worthy,
    alert_dedupe_key,
    target_alert_date,
    build_favorite_alert,
)


def test_target_date_is_tomorrow_in_paris() -> None:
    # 2026-10-12 18:00 UTC = 20:00 Paris → demain = 2026-10-13
    assert target_alert_date(datetime(2026, 10, 12, 18, 0, tzinfo=UTC)) == "2026-10-13"


def test_target_date_uses_paris_day_not_utc_day() -> None:
    # 2026-10-12 23:30 UTC = 2026-10-13 01:30 Paris → demain = 2026-10-14
    assert target_alert_date(datetime(2026, 10, 12, 23, 30, tzinfo=UTC)) == "2026-10-14"


def test_only_high_verdict_is_alert_worthy() -> None:
    assert is_alert_worthy("high") is True
    for verdict in ("medium", "low", "none", ""):
        assert is_alert_worthy(verdict) is False


def test_message_mentions_peak_score_and_hour_in_french_by_default() -> None:
    title, body = build_favorite_alert("Mont Aiguille", 87)
    assert title == "Mer de nuage demain"
    assert body == f"Conditions idéales prévues demain {ALERT_HOUR}h sur Mont Aiguille — 87% 🟢"
    assert build_favorite_alert("Mont Aiguille", 87, "fr") == (title, body)


def test_message_is_localized_in_english() -> None:
    title, body = build_favorite_alert("Mont Aiguille", 87, "en")
    assert title == "Cloud sea tomorrow"
    assert body == "Ideal conditions forecast tomorrow at 6 am at Mont Aiguille — 87% 🟢"


def test_unknown_or_missing_locale_falls_back_to_french() -> None:
    assert resolve_locale(None) == "fr"
    assert resolve_locale("de") == "fr"
    assert resolve_locale("en") == "en"
    assert build_favorite_alert("X", 80, "de") == build_favorite_alert("X", 80, "fr")


def test_dedupe_key_is_prefixed_and_scoped_per_user_peak_and_date() -> None:
    key = alert_dedupe_key("user-1", "peak-9", "2026-10-13")
    assert key == "notif:fav:user-1:peak-9:2026-10-13"
    assert key != alert_dedupe_key("user-2", "peak-9", "2026-10-13")
    assert key != alert_dedupe_key("user-1", "peak-9", "2026-10-14")


def test_short_peak_name_is_unchanged() -> None:
    assert "Mont Aiguille" in build_favorite_alert("Mont Aiguille", 87)[1]
    assert "…" not in build_favorite_alert("Mont Aiguille", 87)[1]


def test_peak_name_of_exactly_80_characters_is_unchanged() -> None:
    name = "a" * 80
    for locale in ("fr", "en"):
        body = build_favorite_alert(name, 87, locale)[1]
        assert name in body and "…" not in body.replace("—", "")


@pytest.mark.parametrize("locale", ["fr", "en"])
def test_long_peak_name_is_truncated_with_an_ellipsis(locale: str) -> None:
    body = build_favorite_alert("a" * 5000, 87, locale)[1]
    assert "a" * 80 + "…" in body
    assert "a" * 81 not in body
    assert len(body) < 200
