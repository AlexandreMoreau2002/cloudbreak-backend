from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_redis
from app.db.session import get_db
from app.main import app


def test_admin_routes_are_registered() -> None:
    paths = {
        path
        for route in app.routes
        for path in [
            getattr(route, "path", None),
            *[
                child.path
                for child in getattr(getattr(route, "original_router", None), "routes", [])
            ],
        ]
        if path is not None
    }
    assert "/api/v1/admin/overview" in paths
    assert "/internal/server-metrics" in paths


def setup_function() -> None:
    app.dependency_overrides.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_overview_without_token_is_forbidden() -> None:
    response = TestClient(app).get("/api/v1/admin/overview")
    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_FORBIDDEN"


def test_unknown_heartbeat_is_not_found() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", "s" * 32):
        response = TestClient(app).post(
            "/internal/heartbeats/unknown",
            headers={"X-Cron-Secret": "s" * 32},
            json={"status": "ok"},
        )
    assert response.status_code == 404
    assert response.json()["code"] == "HEARTBEAT_UNKNOWN_JOB"


def test_metrics_rejects_stale_sample() -> None:
    redis = AsyncMock()
    app.dependency_overrides[get_redis] = lambda: redis
    with patch("app.core.dependencies.settings.internal_cron_secret", "s" * 32):
        response = TestClient(app).post(
            "/internal/server-metrics",
            headers={"X-Cron-Secret": "s" * 32},
            json={
                "sampled_at": (datetime.now(UTC) - timedelta(minutes=6)).isoformat(),
                "cpu_load_1m": 0,
                "cpu_count": 1,
                "mem_total_mb": 1,
                "mem_available_mb": 1,
                "swap_total_mb": 0,
                "swap_used_mb": 0,
                "disk_total_gb": 1,
                "disk_used_gb": 0,
            },
        )
    assert response.status_code == 422


def test_heartbeat_nominal_returns_204_and_writes_record() -> None:
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = None
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.core.dependencies.settings.internal_cron_secret", "s" * 32):
        response = TestClient(app).post(
            "/internal/heartbeats/purge",
            headers={"X-Cron-Secret": "s" * 32},
            json={"status": "ok"},
        )
    assert response.status_code == 204
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


def test_heartbeat_rejects_missing_and_invalid_secrets() -> None:
    with patch("app.core.dependencies.settings.internal_cron_secret", ""):
        disabled = TestClient(app).post("/internal/heartbeats/purge", json={"status": "ok"})
    with patch("app.core.dependencies.settings.internal_cron_secret", "s" * 32):
        invalid = TestClient(app).post(
            "/internal/heartbeats/purge",
            headers={"X-Cron-Secret": "invalid"},
            json={"status": "ok"},
        )
    assert disabled.status_code == 503
    assert invalid.status_code == 403


def test_server_metrics_nominal_writes_redis_and_caps_history() -> None:
    redis = AsyncMock()
    app.dependency_overrides[get_redis] = lambda: redis
    payload = {
        "sampled_at": datetime.now(UTC).isoformat(),
        "cpu_load_1m": 0.35,
        "cpu_count": 2,
        "mem_total_mb": 3819,
        "mem_available_mb": 1474,
        "swap_total_mb": 4095,
        "swap_used_mb": 1929,
        "disk_total_gb": 78,
        "disk_used_gb": 44.5,
    }
    with patch("app.core.dependencies.settings.internal_cron_secret", "s" * 32):
        response = TestClient(app).post(
            "/internal/server-metrics", headers={"X-Cron-Secret": "s" * 32}, json=payload
        )
    assert response.status_code == 204
    redis.set.assert_awaited_once()
    redis.ltrim.assert_awaited_once_with("ops:server_metrics:history", 0, 95)
