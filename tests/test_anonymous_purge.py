"""Tests du service de purge des comptes anonymes inactifs."""

import pytest
from sqlalchemy.dialects import postgresql
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.core.security import SupabaseAdminError
from app.services.anonymous_purge import (
    LOCK_KEY,
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
    assert "order by max(" in sql
    assert "asc" in sql
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
async def test_supabase_account_is_deleted_before_local_data() -> None:
    db = _db(["anon-1"])
    order: list[str] = []

    with (
        patch(f"{MODULE}.get_supabase_user", new=AsyncMock(return_value={"is_anonymous": True})),
        patch(
            f"{MODULE}.delete_supabase_user",
            new=AsyncMock(side_effect=lambda *a: order.append("supabase")),
        ),
        patch(
            f"{MODULE}.delete_user_data",
            new=AsyncMock(side_effect=lambda *a: order.append("local")),
        ),
        patch(f"{MODULE}.QuotaService") as quota_cls,
    ):
        quota_cls.return_value.delete_user_keys = AsyncMock(
            side_effect=lambda *a: order.append("quota")
        )
        await purge_inactive_anonymous_accounts(
            db,
            _LockRedis(),
            retention_days=30,
            max_per_run=200,
            dry_run=False,
            supabase_url=URL,
            service_role_key=KEY,
            now=NOW,
        )

    assert order == ["supabase", "local", "quota"]


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
    # Supabase a échoué pour « fail-delete » : rien n'est supprimé localement, il sera rejoué.
    assert delete_data.await_args_list == [call("ok", db)]
    assert delete_supabase.await_count == 2
    db.rollback.assert_not_awaited()


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
    # Supabase passe avant le local : les deux comptes Supabase sont supprimés.
    assert delete_supabase.await_args_list == [call("a", URL, KEY), call("b", URL, KEY)]
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_failure_after_supabase_is_repaired_on_the_next_run() -> None:
    """1er passage : Supabase supprimé, local en échec. 2e passage : 404 → purge locale."""
    db = _db(["a"])
    supabase_state: dict[str, object] = {"a": {"is_anonymous": True}}

    async def _get(user_id: str, *args: object) -> object:
        return supabase_state[user_id]

    async def _delete_supabase(user_id: str, *args: object) -> None:
        supabase_state[user_id] = None  # le compte n'existe plus chez Supabase

    with (
        patch(f"{MODULE}.get_supabase_user", new=AsyncMock(side_effect=_get)),
        patch(
            f"{MODULE}.delete_supabase_user", new=AsyncMock(side_effect=_delete_supabase)
        ) as delete_supabase,
        patch(
            f"{MODULE}.delete_user_data", new=AsyncMock(side_effect=[RuntimeError("db"), None])
        ) as delete_data,
        patch(f"{MODULE}.QuotaService") as quota_cls,
    ):
        quota_cls.return_value.delete_user_keys = AsyncMock()
        kwargs = dict(
            retention_days=30,
            max_per_run=200,
            dry_run=False,
            supabase_url=URL,
            service_role_key=KEY,
            now=NOW,
        )
        first = await purge_inactive_anonymous_accounts(db, _LockRedis(), **kwargs)  # type: ignore[arg-type]
        second = await purge_inactive_anonymous_accounts(db, _LockRedis(), **kwargs)  # type: ignore[arg-type]

    assert first == PurgeSummary(1, 0, 0, 1, False)
    assert second == PurgeSummary(1, 1, 0, 0, False)
    delete_supabase.assert_awaited_once()
    assert delete_data.await_count == 2
    quota_cls.return_value.delete_user_keys.assert_awaited_once_with("a")


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


class _LockRedis:
    """Redis en mémoire : SET NX et compare-et-supprime (équivalent du script Lua)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool, int | None]] = []

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        self.set_calls.append((key, value, nx, ex))
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        assert numkeys == 1
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class _ReleaseFailsRedis(_LockRedis):
    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        raise ConnectionError("redis down")


async def _purge_with(redis: object, *, dry_run: bool = False) -> PurgeSummary:
    return await purge_inactive_anonymous_accounts(
        AsyncMock(),
        redis,  # type: ignore[arg-type]
        retention_days=30,
        max_per_run=200,
        dry_run=dry_run,
        supabase_url=URL,
        service_role_key=KEY,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_run_is_skipped_when_the_lock_is_held() -> None:
    redis = _LockRedis()
    redis.store[LOCK_KEY] = "other-run"

    with patch(f"{MODULE}.fetch_candidates", new=AsyncMock()) as fetch:
        summary = await _purge_with(redis)

    assert summary == PurgeSummary(skipped_locked=1)
    fetch.assert_not_awaited()
    assert redis.store[LOCK_KEY] == "other-run"
    key, _, nx, ex = redis.set_calls[0]
    assert key == "lock:anon-purge"
    assert nx is True
    assert ex == 300


@pytest.mark.asyncio
async def test_lock_holds_a_unique_token_and_is_released_after_a_normal_run() -> None:
    redis = _LockRedis()
    seen: list[str] = []

    async def _fetch(*args: object) -> list[str]:
        seen.append(redis.store[LOCK_KEY])
        return []

    with patch(f"{MODULE}.fetch_candidates", new=_fetch):
        await _purge_with(redis)
        await _purge_with(redis)

    assert len(seen[0]) == 32
    assert seen[0] != seen[1]
    assert LOCK_KEY not in redis.store


@pytest.mark.asyncio
async def test_lock_is_released_even_if_the_run_raises() -> None:
    redis = _LockRedis()

    with (
        patch(f"{MODULE}.fetch_candidates", new=AsyncMock(side_effect=RuntimeError("db"))),
        pytest.raises(RuntimeError),
    ):
        await _purge_with(redis)

    assert LOCK_KEY not in redis.store


@pytest.mark.asyncio
async def test_lock_taken_over_by_another_run_is_not_deleted() -> None:
    redis = _LockRedis()

    async def _fetch(*args: object) -> list[str]:
        redis.store[LOCK_KEY] = "other-run"  # notre verrou a expiré, un autre run l'a repris
        return []

    with patch(f"{MODULE}.fetch_candidates", new=_fetch):
        await _purge_with(redis)

    assert redis.store[LOCK_KEY] == "other-run"


@pytest.mark.asyncio
async def test_dry_run_does_not_take_the_lock() -> None:
    redis = _LockRedis()
    redis.store[LOCK_KEY] = "real-run"

    with patch(f"{MODULE}.fetch_candidates", new=AsyncMock(return_value=[])) as fetch:
        summary = await _purge_with(redis, dry_run=True)

    assert summary == PurgeSummary(dry_run=True)
    fetch.assert_awaited_once()
    assert redis.set_calls == []
    assert redis.store[LOCK_KEY] == "real-run"


@pytest.mark.asyncio
async def test_lock_release_failure_does_not_mask_the_original_error() -> None:
    with (
        patch(f"{MODULE}.fetch_candidates", new=AsyncMock(side_effect=RuntimeError("db down"))),
        pytest.raises(RuntimeError, match="db down"),
    ):
        await _purge_with(_ReleaseFailsRedis())


@pytest.mark.asyncio
async def test_lock_release_failure_does_not_break_a_successful_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = _ReleaseFailsRedis()

    with (
        patch(f"{MODULE}.fetch_candidates", new=AsyncMock(return_value=[])),
        caplog.at_level("ERROR"),
    ):
        summary = await _purge_with(redis)

    assert summary.candidates == 0
    assert any(r.message == "anonymous_purge_lock_release_failed" for r in caplog.records)
    assert redis.set_calls[0][1] not in caplog.text
