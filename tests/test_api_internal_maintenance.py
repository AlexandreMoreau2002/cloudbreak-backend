"""Tests de l'endpoint interne de purge des comptes anonymes inactifs."""

from typing import Any
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_redis
from app.services.anonymous_purge import PurgeSummary

SECRET = "s" * 32
URL = "/internal/maintenance/purge-anonymous"
ENDPOINT = "app.api.v1.endpoints.internal_maintenance"


async def _override_db():
    yield AsyncMock()


def _client() -> TestClient:
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _configured() -> tuple[Any, Any, Any]:
    return (
        patch("app.core.dependencies.settings.internal_cron_secret", SECRET),
        patch(f"{ENDPOINT}.settings.supabase_url", "https://supabase.test"),
        patch(f"{ENDPOINT}.settings.supabase_service_role_key", "service-role"),
    )


def test_disabled_when_secret_not_configured_returns_503() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", ""):
        response = _client().post(URL, headers={"X-Cron-Secret": "anything"})
    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_JOBS_DISABLED"


def test_weak_secret_is_treated_as_not_configured_returns_503() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", "short"):
        response = _client().post(URL, headers={"X-Cron-Secret": "short"})
    assert response.status_code == 503


def test_missing_or_wrong_secret_returns_403() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", SECRET):
        client = _client()
        assert client.post(URL).status_code == 403
        wrong = client.post(URL, headers={"X-Cron-Secret": "nope"})
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "INTERNAL_AUTH_FAILED"


def test_user_jwt_alone_is_not_enough() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", SECRET):
        response = _client().post(URL, headers={"Authorization": "Bearer whatever"})
    assert response.status_code == 403


def test_supabase_admin_not_configured_returns_503_without_running_the_job() -> None:
    with (
        patch("app.core.dependencies.settings.internal_cron_secret", SECRET),
        patch(f"{ENDPOINT}.settings.supabase_service_role_key", ""),
        patch(f"{ENDPOINT}.purge_inactive_anonymous_accounts", new=AsyncMock()) as job,
    ):
        response = _client().post(URL, headers={"X-Cron-Secret": SECRET})
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    job.assert_not_awaited()


def test_valid_secret_runs_the_purge_and_returns_the_summary() -> None:
    summary = PurgeSummary(candidates=4, purged=2, skipped_not_anonymous=1, errors=1)
    secret, url, key = _configured()
    with (
        secret,
        url,
        key,
        patch(f"{ENDPOINT}.settings.anon_retention_days", 30),
        patch(f"{ENDPOINT}.settings.anon_purge_max_per_run", 200),
        patch(
            f"{ENDPOINT}.purge_inactive_anonymous_accounts", new=AsyncMock(return_value=summary)
        ) as job,
    ):
        response = _client().post(URL, headers={"X-Cron-Secret": SECRET})
    assert response.status_code == 200
    assert response.json() == {
        "candidates": 4,
        "purged": 2,
        "skipped_not_anonymous": 1,
        "errors": 1,
        "dry_run": False,
        "skipped_locked": 0,
    }
    kwargs = job.await_args.kwargs
    assert kwargs["retention_days"] == 30
    assert kwargs["max_per_run"] == 200
    assert kwargs["dry_run"] is False
    assert kwargs["supabase_url"] == "https://supabase.test"
    assert kwargs["service_role_key"] == "service-role"


def test_dry_run_query_is_forwarded() -> None:
    summary = PurgeSummary(candidates=1, purged=1, dry_run=True)
    secret, url, key = _configured()
    with (
        secret,
        url,
        key,
        patch(
            f"{ENDPOINT}.purge_inactive_anonymous_accounts", new=AsyncMock(return_value=summary)
        ) as job,
    ):
        response = _client().post(f"{URL}?dry_run=true", headers={"X-Cron-Secret": SECRET})
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert job.await_args.kwargs["dry_run"] is True


def test_invalid_dry_run_value_returns_422() -> None:
    secret, url, key = _configured()
    with secret, url, key:
        response = _client().post(f"{URL}?dry_run=peut-etre", headers={"X-Cron-Secret": SECRET})
    assert response.status_code == 422


def test_concurrent_run_returns_200_with_skipped_locked() -> None:
    secret, url, key = _configured()
    with (
        secret,
        url,
        key,
        patch(
            f"{ENDPOINT}.purge_inactive_anonymous_accounts",
            new=AsyncMock(return_value=PurgeSummary(skipped_locked=1)),
        ),
    ):
        response = _client().post(URL, headers={"X-Cron-Secret": SECRET})
    assert response.status_code == 200
    assert response.json()["skipped_locked"] == 1
    assert response.json()["purged"] == 0
