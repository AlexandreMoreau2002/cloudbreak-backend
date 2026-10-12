"""Tests du service d'alertes favoris."""

import pytest
from types import SimpleNamespace
from sqlalchemy.dialects import postgresql
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime, timedelta

from app.services.favorite_alerts import Candidate, fetch_candidates, process_candidates

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)


def _user(uid: str = "u1", locale: str | None = None):
    return SimpleNamespace(
        supabase_user_id=uid,
        push_token="ExponentPushToken[a]",
        push_token_valid=True,
        locale=locale,
    )


def _peak(pid: str = "p1"):
    return SimpleNamespace(
        id=pid, name="Mont Aiguille", slug="mont-aiguille", lat=44.8, lng=5.5, altitude=2085
    )


def _sub(plan="premium", status="active", delta=timedelta(days=10)):
    return SimpleNamespace(plan=plan, status=status, expires_at=NOW + delta)


def _db(rows):
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_keeps_only_active_premium_entitlements() -> None:
    rows = [
        (_user("u-active"), _peak(), _sub()),
        (_user("u-trial"), _peak(), _sub(status="trial")),
        (_user("u-expired"), _peak(), _sub(delta=timedelta(days=-1))),
        (_user("u-revoked"), _peak(), _sub(status="revoked")),
        (_user("u-free"), _peak(), _sub(plan="free", status="none")),
        (_user("u-nosub"), _peak(), None),
    ]
    candidates = await fetch_candidates(_db(rows), NOW)
    assert [c.user.supabase_user_id for c in candidates] == ["u-active", "u-trial"]


@pytest.mark.asyncio
async def test_query_filters_preference_and_valid_token_in_sql() -> None:
    db = _db([])
    await fetch_candidates(db, NOW)
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "notif_favorites is true" in sql
    assert "push_token is not null" in sql
    assert "push_token_valid is true" in sql
    assert "user_favorites" in sql and "subscriptions" in sql and "peaks" in sql


@pytest.mark.asyncio
async def test_query_filters_premium_entitlement_in_sql_before_the_limit() -> None:
    db = _db([])
    await fetch_candidates(db, NOW)
    statement = db.execute.await_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).lower().split())
    assert "left outer join" not in sql
    assert "subscriptions.plan in" in sql
    assert "subscriptions.status in" in sql
    assert "subscriptions.expires_at >" in sql
    compiled = statement.compile(dialect=postgresql.dialect())
    values = [v for v in compiled.params.values() if isinstance(v, list | tuple | set | frozenset)]
    flat = {item for value in values for item in value}
    assert {"premium", "pro", "trial", "active"} <= flat


@pytest.mark.asyncio
async def test_truncation_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    rows = [(_user(f"u{i}"), _peak(), _sub()) for i in range(3)]
    with patch("app.services.favorite_alerts.MAX_ROWS", 3):
        with caplog.at_level("WARNING"):
            await fetch_candidates(_db(rows), NOW)
    assert any(r.message == "favorite_alerts_truncated" for r in caplog.records)


@pytest.mark.asyncio
async def test_no_truncation_warning_below_the_limit(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        await fetch_candidates(_db([(_user(), _peak(), _sub())]), NOW)
    assert not any(r.message == "favorite_alerts_truncated" for r in caplog.records)


DATE = "2026-10-13"


def _redis(claim_results=None):
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=claim_results or [True] * 50)
    return redis


def _weather(raises=False):
    service = AsyncMock()
    if raises:
        service.get_forecast.side_effect = RuntimeError("provider down")
    return service


def _score(verdict="high", score=87):
    return patch(
        "app.services.favorite_alerts.calculate_score",
        return_value={"score": score, "verdict": verdict},
    )


@pytest.mark.asyncio
async def test_sends_alert_for_high_verdict_and_claims_dedupe_key() -> None:
    send = AsyncMock(return_value=True)
    redis = _redis()
    with _score():
        summary = await process_candidates(
            [Candidate(_user(), _peak())],
            redis=redis,
            weather_service=_weather(),
            date=DATE,
            send=send,
        )
    assert summary.alerts_sent == 1
    send.assert_awaited_once()
    args = send.await_args.args
    assert args[1] == "Mer de nuage demain"
    assert args[2] == "Conditions idéales prévues demain 6h sur Mont Aiguille — 87% 🟢"
    assert args[3] == {"type": "favorite_alert", "slug": "mont-aiguille", "peak_id": "p1"}
    assert redis.set.await_args.args[0] == "notif:fav:u1:p1:2026-10-13"
    assert redis.set.await_args.kwargs == {"nx": True, "ex": 36 * 3600}


@pytest.mark.asyncio
async def test_alert_is_sent_in_the_user_language() -> None:
    send = AsyncMock(return_value=True)
    with _score():
        await process_candidates(
            [Candidate(_user(locale="en"), _peak())],
            redis=_redis(),
            weather_service=_weather(),
            date=DATE,
            send=send,
        )
    assert send.await_args.args[1] == "Cloud sea tomorrow"
    assert (
        send.await_args.args[2]
        == "Ideal conditions forecast tomorrow at 6 am at Mont Aiguille — 87% 🟢"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["medium", "low", "none"])
async def test_no_alert_and_no_claim_when_not_ideal(verdict: str) -> None:
    send, redis = AsyncMock(), _redis()
    with _score(verdict=verdict):
        summary = await process_candidates(
            [Candidate(_user(), _peak())],
            redis=redis,
            weather_service=_weather(),
            date=DATE,
            send=send,
        )
    assert summary.skipped_not_ideal == 1 and summary.alerts_sent == 0
    send.assert_not_awaited()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_sent_is_skipped() -> None:
    send = AsyncMock()
    with _score():
        summary = await process_candidates(
            [Candidate(_user(), _peak())],
            redis=_redis([None]),
            weather_service=_weather(),
            date=DATE,
            send=send,
        )
    assert summary.skipped_already_sent == 1
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_send_releases_the_claim_for_a_retry() -> None:
    redis = _redis()
    with _score():
        summary = await process_candidates(
            [Candidate(_user(), _peak())],
            redis=redis,
            weather_service=_weather(),
            date=DATE,
            send=AsyncMock(return_value=False),
        )
    assert summary.send_failed == 1
    redis.delete.assert_awaited_once_with("notif:fav:u1:p1:2026-10-13")


@pytest.mark.asyncio
async def test_peak_is_scored_once_even_with_several_users() -> None:
    weather = _weather()
    candidates = [Candidate(_user("u1"), _peak()), Candidate(_user("u2"), _peak())]
    with _score():
        summary = await process_candidates(
            candidates,
            redis=_redis(),
            weather_service=weather,
            date=DATE,
            send=AsyncMock(return_value=True),
        )
    assert weather.get_forecast.await_count == 1
    assert summary.peaks_scored == 1 and summary.alerts_sent == 2


@pytest.mark.asyncio
async def test_weather_failure_on_one_peak_does_not_block_others() -> None:
    weather = AsyncMock()
    weather.get_forecast.side_effect = [RuntimeError("down"), object()]
    candidates = [Candidate(_user("u1"), _peak("p1")), Candidate(_user("u2"), _peak("p2"))]
    with _score():
        summary = await process_candidates(
            candidates,
            redis=_redis(),
            weather_service=weather,
            date=DATE,
            send=AsyncMock(return_value=True),
        )
    assert summary.weather_failed == 1 and summary.alerts_sent == 1


@pytest.mark.asyncio
async def test_run_is_capped() -> None:
    from app.services import favorite_alerts

    candidates = [Candidate(_user(f"u{i}"), _peak()) for i in range(5)]
    with _score(), patch.object(favorite_alerts, "MAX_ALERTS_PER_RUN", 2):
        summary = await process_candidates(
            candidates,
            redis=_redis(),
            weather_service=_weather(),
            date=DATE,
            send=AsyncMock(return_value=True),
        )
    assert summary.alerts_sent == 2 and summary.skipped_cap == 3
