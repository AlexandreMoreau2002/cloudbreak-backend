from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_redis, require_admin
from app.db.session import get_db
from app.main import app


def test_admin_overview_writes_an_audit_entry_for_each_successful_call() -> None:
    db = AsyncMock(spec=AsyncSession)
    app.dependency_overrides[require_admin] = lambda: {"id": "admin-id"}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    response_body = {
        "generated_at": "2026-11-23T00:00:00Z",
        "kpis": {"users_total": {"value": 3, "delta_7d": None}},
        "checks_daily": [],
        "series_90d": [{"date": "2026-11-23", "users_total": None}],
        "crons": [],
        "server": {},
    }
    with patch("app.api.v1.endpoints.admin.build_overview", AsyncMock(return_value=response_body)):
        response = TestClient(app).get("/api/v1/admin/overview")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == response_body
    assert response.json()["kpis"]["users_total"]["delta_7d"] is None
    assert "users_total" in response.json()["series_90d"][0]
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


def test_admin_overview_rolls_back_before_auditing_an_error() -> None:
    db = AsyncMock(spec=AsyncSession)
    app.dependency_overrides[require_admin] = lambda: {"id": "admin-id"}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    with patch("app.api.v1.endpoints.admin.build_overview", AsyncMock(side_effect=RuntimeError)):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/admin/overview")
    app.dependency_overrides.clear()
    assert response.status_code == 500
    db.rollback.assert_awaited_once()
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
