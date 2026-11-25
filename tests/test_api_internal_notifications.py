"""Tests de l'endpoint interne des alertes favoris."""

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_redis
from app.services.favorite_alerts import AlertSummary

SECRET = "s" * 32
URL = "/internal/notifications/run-favorites"


async def _override_db():
    yield AsyncMock()


def _client() -> TestClient:
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_disabled_when_secret_not_configured_returns_503() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", ""):
        response = _client().post(URL, headers={"X-Cron-Secret": "anything"})
    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_JOBS_DISABLED"


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


def test_valid_secret_runs_the_job_and_returns_the_summary() -> None:
    summary = AlertSummary(candidates=3, peaks_scored=2, alerts_sent=1, skipped_not_ideal=2)
    with (
        patch("app.core.dependencies.settings.internal_cron_secret", SECRET),
        patch(
            "app.api.v1.endpoints.internal_notifications.run_favorite_alerts",
            new=AsyncMock(return_value=summary),
        ) as job,
    ):
        response = _client().post(URL, headers={"X-Cron-Secret": SECRET})
    assert response.status_code == 200
    assert response.json() == {
        "candidates": 3,
        "peaks_scored": 2,
        "alerts_sent": 1,
        "skipped_not_ideal": 2,
        "skipped_already_sent": 0,
        "skipped_cap": 0,
        "send_failed": 0,
        "weather_failed": 0,
        "skipped_locked": 0,
        "skipped_circuit_open": 0,
    }
    job.assert_awaited_once()


def test_weak_secret_is_treated_as_not_configured_returns_503() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", "short"):
        response = _client().post(URL, headers={"X-Cron-Secret": "short"})
    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_JOBS_DISABLED"
