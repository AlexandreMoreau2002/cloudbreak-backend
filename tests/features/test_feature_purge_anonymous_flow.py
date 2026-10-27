"""Feature test — flux HTTP complet POST /internal/maintenance/purge-anonymous.

La base et Supabase sont simulés ; le service de purge réel tourne de bout en bout.
"""

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_redis

SECRET = "s" * 32
URL = "/internal/maintenance/purge-anonymous"
SERVICE = "app.services.anonymous_purge"
ENDPOINT = "app.api.v1.endpoints.internal_maintenance"
SUPABASE = {
    "anon-old": {"id": "anon-old", "is_anonymous": True},
    "perm-old": {"id": "perm-old", "is_anonymous": False},
    "gone-old": None,
}


def _db() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(SUPABASE)
    db.execute.return_value = result
    return db


def _redis() -> MagicMock:
    async def _no_keys(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        return
        yield

    redis = MagicMock()
    redis.scan_iter = MagicMock(side_effect=_no_keys)
    return redis


def _post(path: str) -> tuple[dict[str, object], AsyncMock, AsyncMock]:
    db = _db()

    async def _override_db():  # type: ignore[no-untyped-def]
        yield db

    async def _get(user_id: str, *args: object) -> object:
        return SUPABASE[user_id]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _redis
    try:
        with (
            patch("app.core.dependencies.settings.internal_cron_secret", SECRET),
            patch(f"{ENDPOINT}.settings.supabase_url", "https://supabase.test"),
            patch(f"{ENDPOINT}.settings.supabase_service_role_key", "service-role"),
            patch(f"{SERVICE}.get_supabase_user", new=AsyncMock(side_effect=_get)),
            patch(f"{SERVICE}.delete_user_data", new=AsyncMock()) as delete_data,
            patch(f"{SERVICE}.delete_supabase_user", new=AsyncMock()) as delete_supabase,
            TestClient(app) as client,
        ):
            response = client.post(path, headers={"X-Cron-Secret": SECRET})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body, delete_data, delete_supabase


def test_dry_run_then_real_purge_flow() -> None:
    body, delete_data, delete_supabase = _post(f"{URL}?dry_run=true")
    assert body == {
        "candidates": 3,
        "purged": 2,
        "skipped_not_anonymous": 1,
        "errors": 0,
        "dry_run": True,
    }
    delete_data.assert_not_awaited()
    delete_supabase.assert_not_awaited()

    body, delete_data, delete_supabase = _post(URL)
    assert body["purged"] == 2
    assert body["dry_run"] is False
    purged_locally = sorted(c.args[0] for c in delete_data.await_args_list)
    assert purged_locally == ["anon-old", "gone-old"]
    delete_supabase.assert_awaited_once()
    assert delete_supabase.await_args.args[0] == "anon-old"
    assert "anon-old" not in str(body)
