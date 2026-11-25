"""Tests pour le endpoint /health."""

from app.main import app
from app.db.session import get_db
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from app.core.dependencies import get_redis
from unittest.mock import AsyncMock, MagicMock


def _make_db_ok() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


def _make_db_down() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OperationalError("conn", None, None))
    return db


def _make_redis_ok() -> AsyncMock:
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    return redis


def _make_redis_down() -> AsyncMock:
    redis = AsyncMock()
    redis.ping = AsyncMock(side_effect=Exception("redis unavailable"))
    return redis


def test_health_all_ok() -> None:
    app.dependency_overrides[get_db] = lambda: _make_db_ok()
    app.dependency_overrides[get_redis] = lambda: _make_redis_ok()

    client = TestClient(app)
    response = client.get("/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {"database": "ok", "redis": "ok"},
    }


def test_health_degraded_db_down() -> None:
    app.dependency_overrides[get_db] = lambda: _make_db_down()
    app.dependency_overrides[get_redis] = lambda: _make_redis_ok()

    client = TestClient(app)
    response = client.get("/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["database"] == "unavailable"
    assert body["services"]["redis"] == "ok"


def test_health_degraded_redis_down() -> None:
    app.dependency_overrides[get_db] = lambda: _make_db_ok()
    app.dependency_overrides[get_redis] = lambda: _make_redis_down()

    client = TestClient(app)
    response = client.get("/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["database"] == "ok"
    assert body["services"]["redis"] == "unavailable"
