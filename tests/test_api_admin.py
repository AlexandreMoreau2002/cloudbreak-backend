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


from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import get_redis
from app.main import app


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
