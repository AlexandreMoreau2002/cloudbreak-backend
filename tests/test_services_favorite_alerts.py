"""Tests du service d'alertes favoris."""

import pytest
from types import SimpleNamespace
from sqlalchemy.dialects import postgresql
from unittest.mock import AsyncMock, MagicMock
from datetime import UTC, datetime, timedelta

from app.services.favorite_alerts import fetch_candidates

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
