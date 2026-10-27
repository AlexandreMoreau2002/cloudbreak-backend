"""Tests du service de purge des comptes anonymes inactifs."""

import pytest
from sqlalchemy.dialects import postgresql
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.core.security import SupabaseAdminError
from app.services.anonymous_purge import (
    PurgeSummary,
    build_candidates_query,
    fetch_candidates,
    purge_inactive_anonymous_accounts,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
MODULE = "app.services.anonymous_purge"
URL = "https://supabase.test"
KEY = "service-role"


def _db(user_ids: list[str]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = user_ids
    db.execute.return_value = result
    return db


async def _run(
    db: AsyncMock,
    *,
    supabase: dict[str, object],
    dry_run: bool = False,
    max_per_run: int = 200,
) -> tuple[PurgeSummary, AsyncMock, AsyncMock, AsyncMock]:
    """Lance la purge avec Supabase simulé : `supabase[user_id]` = réponse ou exception."""

    async def _get(user_id: str, supabase_url: str, service_role_key: str) -> object:
        value = supabase[user_id]
        if isinstance(value, Exception):
            raise value
        return value

    with (
        patch(f"{MODULE}.get_supabase_user", new=AsyncMock(side_effect=_get)),
        patch(f"{MODULE}.delete_user_data", new=AsyncMock()) as delete_data,
        patch(f"{MODULE}.delete_supabase_user", new=AsyncMock()) as delete_supabase,
        patch(f"{MODULE}.QuotaService") as quota_cls,
    ):
        quota_cls.return_value.delete_user_keys = AsyncMock()
        summary = await purge_inactive_anonymous_accounts(
            db,
            AsyncMock(),
            retention_days=30,
            max_per_run=max_per_run,
            dry_run=dry_run,
            supabase_url=URL,
            service_role_key=KEY,
            now=NOW,
        )
    return summary, delete_data, delete_supabase, quota_cls.return_value.delete_user_keys


def _sql(max_per_run: int = 200) -> str:
    statement = build_candidates_query(NOW - timedelta(days=30), max_per_run)
    compiled = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return " ".join(str(compiled).lower().split())


def test_candidates_query_unions_the_three_activity_tables() -> None:
    sql = _sql()
    assert "union all" in sql
    assert "from predictions" in sql
    assert "from terrain_validations" in sql
    assert "from user_favorites" in sql
    assert "predictions.created_at" in sql
    assert "terrain_validations.validated_at" in sql
    assert "user_favorites.created_at" in sql


def test_candidates_query_uses_last_activity_and_excludes_provisioned_users() -> None:
    sql = _sql(max_per_run=7)
    assert "left outer join users" in sql
    assert "users.supabase_user_id is null" in sql
    assert "group by" in sql
    assert "having max(" in sql
    assert "2026-09-27" in sql  # cutoff = now - 30 j
    assert "order by max(" in sql and "asc" in sql
    assert "limit 7" in sql


@pytest.mark.asyncio
async def test_fetch_candidates_returns_user_ids() -> None:
    db = _db(["a", "b"])

    assert await fetch_candidates(db, NOW, 10) == ["a", "b"]
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_inactive_anonymous_candidate_is_purged() -> None:
    db = _db(["anon-1"])

    summary, delete_data, delete_supabase, delete_keys = await _run(
        db, supabase={"anon-1": {"id": "anon-1", "is_anonymous": True}}
    )

    assert summary == PurgeSummary(
        candidates=1, purged=1, skipped_not_anonymous=0, errors=0, dry_run=False
    )
    delete_data.assert_awaited_once_with("anon-1", db)
    delete_keys.assert_awaited_once_with("anon-1")
    delete_supabase.assert_awaited_once_with("anon-1", URL, KEY)


@pytest.mark.asyncio
async def test_recent_activity_is_not_a_candidate() -> None:
    # La sélection SQL écarte les actifs récents : aucune ligne → rien n'est fait.
    db = _db([])

    summary, delete_data, delete_supabase, _ = await _run(db, supabase={})

    assert summary == PurgeSummary(0, 0, 0, 0, False)
    delete_data.assert_not_awaited()
    delete_supabase.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supabase_user",
    [
        {"id": "perm", "is_anonymous": False},
        {"id": "perm"},
        {"id": "perm", "is_anonymous": "true"},
        {"id": "perm", "is_anonymous": 1},
    ],
)
async def test_permanent_account_is_never_deleted(supabase_user: dict[str, object]) -> None:
    db = _db(["perm"])

    summary, delete_data, delete_supabase, delete_keys = await _run(
        db, supabase={"perm": supabase_user}
    )

    assert summary == PurgeSummary(1, 0, 1, 0, False)
    delete_data.assert_not_awaited()
    delete_keys.assert_not_awaited()
    delete_supabase.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_already_absent_from_supabase_purges_local_data_only() -> None:
    db = _db(["gone"])

    summary, delete_data, delete_supabase, delete_keys = await _run(db, supabase={"gone": None})

    assert summary == PurgeSummary(1, 1, 0, 0, False)
    delete_data.assert_awaited_once_with("gone", db)
    delete_keys.assert_awaited_once_with("gone")
    delete_supabase.assert_not_awaited()


@pytest.mark.asyncio
async def test_supabase_lookup_error_counts_error_and_deletes_nothing() -> None:
    db = _db(["x"])

    summary, delete_data, delete_supabase, delete_keys = await _run(
        db, supabase={"x": SupabaseAdminError("boom")}
    )

    assert summary == PurgeSummary(1, 0, 0, 1, False)
    delete_data.assert_not_awaited()
    delete_keys.assert_not_awaited()
    delete_supabase.assert_not_awaited()


@pytest.mark.asyncio
async def test_max_per_run_is_passed_to_the_query() -> None:
    db = _db(["a"])

    await _run(db, supabase={"a": None}, max_per_run=3)

    statement = db.execute.await_args.args[0]
    assert statement._limit_clause.value == 3


@pytest.mark.asyncio
async def test_dry_run_takes_the_same_decisions_without_deleting() -> None:
    db = _db(["anon", "perm", "gone", "err"])

    summary, delete_data, delete_supabase, delete_keys = await _run(
        db,
        dry_run=True,
        supabase={
            "anon": {"is_anonymous": True},
            "perm": {"is_anonymous": False},
            "gone": None,
            "err": SupabaseAdminError("boom"),
        },
    )

    assert summary == PurgeSummary(
        candidates=4, purged=2, skipped_not_anonymous=1, errors=1, dry_run=True
    )
    delete_data.assert_not_awaited()
    delete_keys.assert_not_awaited()
    delete_supabase.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_failure_does_not_stop_the_following_candidates() -> None:
    db = _db(["err", "fail-delete", "ok"])

    async def _get(user_id: str, supabase_url: str, service_role_key: str) -> object:
        if user_id == "err":
            raise SupabaseAdminError("boom")
        return {"is_anonymous": True}

    async def _delete_supabase(user_id: str, *args: object) -> None:
        if user_id == "fail-delete":
            raise RuntimeError("supabase down")

    with (
        patch(f"{MODULE}.get_supabase_user", new=AsyncMock(side_effect=_get)),
        patch(f"{MODULE}.delete_user_data", new=AsyncMock()) as delete_data,
        patch(
            f"{MODULE}.delete_supabase_user", new=AsyncMock(side_effect=_delete_supabase)
        ) as delete_supabase,
        patch(f"{MODULE}.QuotaService") as quota_cls,
    ):
        quota_cls.return_value.delete_user_keys = AsyncMock()
        summary = await purge_inactive_anonymous_accounts(
            db,
            AsyncMock(),
            retention_days=30,
            max_per_run=200,
            dry_run=False,
            supabase_url=URL,
            service_role_key=KEY,
        )

    assert summary == PurgeSummary(3, 1, 0, 2, False)
    assert delete_data.await_args_list == [call("fail-delete", db), call("ok", db)]
    assert delete_supabase.await_count == 2
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_deletion_failure_rolls_back_and_continues() -> None:
    db = _db(["a", "b"])

    with (
        patch(f"{MODULE}.get_supabase_user", new=AsyncMock(return_value={"is_anonymous": True})),
        patch(f"{MODULE}.delete_user_data", new=AsyncMock(side_effect=[RuntimeError("db"), None])),
        patch(f"{MODULE}.delete_supabase_user", new=AsyncMock()) as delete_supabase,
        patch(f"{MODULE}.QuotaService") as quota_cls,
    ):
        quota_cls.return_value.delete_user_keys = AsyncMock()
        summary = await purge_inactive_anonymous_accounts(
            db,
            AsyncMock(),
            retention_days=30,
            max_per_run=200,
            dry_run=False,
            supabase_url=URL,
            service_role_key=KEY,
            now=NOW,
        )

    assert summary == PurgeSummary(2, 1, 0, 1, False)
    # Données locales non supprimées → Supabase non plus pour ce candidat.
    delete_supabase.assert_awaited_once_with("b", URL, KEY)
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_logs_contain_counters_but_never_user_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _db(["anon-secret-id", "perm-secret-id", "err-secret-id"])

    with caplog.at_level("DEBUG", logger=MODULE):
        await _run(
            db,
            supabase={
                "anon-secret-id": {"is_anonymous": True},
                "perm-secret-id": {"is_anonymous": False},
                "err-secret-id": SupabaseAdminError("boom"),
            },
        )

    done = [r for r in caplog.records if r.getMessage() == "anonymous_purge_done"]
    assert len(done) == 1
    assert done[0].__dict__["purged"] == 1
    assert done[0].__dict__["errors"] == 1
    for record in caplog.records:
        rendered = record.getMessage() + repr(record.__dict__)
        assert "secret-id" not in rendered
        assert KEY not in rendered
