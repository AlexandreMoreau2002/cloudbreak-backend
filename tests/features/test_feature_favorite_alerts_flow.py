"""
Tests du flux complet des alertes favoris (story 5.2), sans réseau ni base.

Cas testés:
  1. Premier passage → 1 alerte envoyée
  2. Second passage identique → 0 alerte (déduplication Redis)
  3. Envoi en échec puis réussi au passage suivant (clé relâchée)
  4. Utilisateur non Premium ou absent de la sélection SQL → aucune alerte
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime, timedelta

from app.services.favorite_alerts import fetch_candidates, process_candidates

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)
DATE = "2026-10-13"


class _FakeRedis:
    """Redis en mémoire : seulement `set(nx, ex)` et `delete`."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _user(uid: str):
    return SimpleNamespace(
        supabase_user_id=uid, push_token="ExponentPushToken[a]", push_token_valid=True, locale=None
    )


def _peak():
    return SimpleNamespace(
        id="p1", name="Mont Aiguille", slug="mont-aiguille", lat=44.8, lng=5.5, altitude=2085
    )


def _sub(plan: str = "premium", status: str = "active"):
    return SimpleNamespace(plan=plan, status=status, expires_at=NOW + timedelta(days=5))


def _db(rows):
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute.return_value = result
    return db


def _high_score():
    return patch(
        "app.services.favorite_alerts.calculate_score",
        return_value={"score": 87, "verdict": "high"},
    )


async def _run(db, redis, send):
    candidates = await fetch_candidates(db, NOW)
    return await process_candidates(
        candidates, redis=redis, weather_service=AsyncMock(), date=DATE, send=send
    )


@pytest.mark.asyncio
async def test_first_run_sends_and_second_identical_run_is_deduplicated() -> None:
    db, redis, send = (
        _db([(_user("u1"), _peak(), _sub())]),
        _FakeRedis(),
        AsyncMock(return_value=True),
    )
    with _high_score():
        first = await _run(db, redis, send)
        second = await _run(db, redis, send)
    assert first.alerts_sent == 1
    assert second.alerts_sent == 0 and second.skipped_already_sent == 1
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_send_is_retried_on_the_next_run() -> None:
    db, redis = _db([(_user("u1"), _peak(), _sub())]), _FakeRedis()
    send = AsyncMock(side_effect=[False, True])
    with _high_score():
        first = await _run(db, redis, send)
        second = await _run(db, redis, send)
    assert first.send_failed == 1 and first.alerts_sent == 0
    assert second.alerts_sent == 1
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_non_premium_and_unselected_users_get_no_alert() -> None:
    # `notif_favorites=False` est filtré en SQL : la ligne n'est jamais retournée.
    rows = [
        (_user("u-free"), _peak(), _sub(plan="free", status="none")),
        (_user("u-expired"), _peak(), _sub(status="expired")),
        (_user("u-nosub"), _peak(), None),
    ]
    send = AsyncMock(return_value=True)
    with _high_score():
        summary = await _run(_db(rows), _FakeRedis(), send)
    assert summary.candidates == 0 and summary.alerts_sent == 0
    send.assert_not_awaited()
    no_rows = await _run(_db([]), _FakeRedis(), send)
    assert no_rows.candidates == 0
    send.assert_not_awaited()
