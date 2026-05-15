import sys
import runpy
import pytest
import inspect
from app.db import seed_test_users
from unittest.mock import AsyncMock, MagicMock, patch


class _AsyncContextManager:
    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    def add(self, obj: object) -> None:
        self.added.append(obj)


class _FakeEngine:
    def __init__(self) -> None:
        self.conn = MagicMock()
        self.conn.run_sync = AsyncMock()
        self.dispose = AsyncMock()

    def begin(self) -> _AsyncContextManager:
        return _AsyncContextManager(self.conn)


def _install_fake_db(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeEngine, _FakeSession]:
    engine = _FakeEngine()
    session = _FakeSession()

    monkeypatch.setattr(seed_test_users, "create_async_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(
        seed_test_users,
        "async_sessionmaker",
        lambda *args, **kwargs: (lambda: _AsyncContextManager(session)),
    )

    return engine, session


@pytest.mark.asyncio
async def test_seed_test_users_inserts_all_test_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session = _install_fake_db(monkeypatch)

    await seed_test_users.seed_test_users()

    assert len(session.added) == len(seed_test_users.TEST_USERS)
    assert {item.user_id for item in session.added} == {
        str(user["user_id"]) for user in seed_test_users.TEST_USERS.values()
    }
    assert {item.plan for item in session.added} == {
        str(user["plan"]) for user in seed_test_users.TEST_USERS.values()
    }
    session.commit.assert_awaited_once()
    engine.conn.run_sync.assert_awaited_once_with(seed_test_users.Subscription.metadata.create_all)
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_unseed_test_users_deletes_all_test_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, session = _install_fake_db(monkeypatch)

    await seed_test_users.unseed_test_users()

    assert session.execute.await_count == len(seed_test_users.TEST_USERS)
    assert session.commit.await_count == 1
    engine.dispose.assert_awaited_once()


def test_main_runs_seed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_seed() -> None:
        return None

    seed_coro = fake_seed()

    monkeypatch.setattr(sys, "argv", ["seed_test_users.py"])
    monkeypatch.setattr(seed_test_users, "seed_test_users", MagicMock(return_value=seed_coro))

    with patch("app.db.seed_test_users.asyncio.run") as run:
        seed_test_users.main()

    run.assert_called_once_with(seed_coro)
    seed_coro.close()


def test_main_runs_unseed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_unseed() -> None:
        return None

    unseed_coro = fake_unseed()

    monkeypatch.setattr(sys, "argv", ["seed_test_users.py", "unseed"])
    monkeypatch.setattr(seed_test_users, "unseed_test_users", MagicMock(return_value=unseed_coro))

    with patch("app.db.seed_test_users.asyncio.run") as run:
        seed_test_users.main()

    run.assert_called_once_with(unseed_coro)
    unseed_coro.close()


def test_main_exits_on_unknown_action(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["seed_test_users.py", "invalid"])

    with pytest.raises(SystemExit) as exc_info:
        seed_test_users.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Unknown action: invalid" in captured.out
    assert "Usage: python -m app.db.seed_test_users [seed|unseed]" in captured.out


def test_module_main_guard_invokes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["seed_test_users.py"])

    with patch("asyncio.run") as run:
        runpy.run_module("app.db.seed_test_users", run_name="__main__")

    run.assert_called_once()
    assert inspect.iscoroutine(run.call_args.args[0])
    run.call_args.args[0].close()
