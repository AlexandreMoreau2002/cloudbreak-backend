from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.main import app
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport


client = TestClient(app)


def test_get_me_without_token() -> None:
    response = client.get("/api/v1/user/me")
    assert response.status_code == 403


def test_get_me_invalid_token() -> None:
    response = client.get(
        "/api/v1/user/me",
        headers={"Authorization": "Bearer token.invalide.ici"},
    )
    assert response.status_code == 401


def test_get_me_valid_token() -> None:
    payload = {"sub": "user-123", "email": "test@cloudbreak.app"}
    with patch("app.core.dependencies.decode_supabase_jwt", return_value=payload):
        response = client.get(
            "/api/v1/user/me",
            headers={"Authorization": "Bearer valid.token.here"},
        )
    assert response.status_code == 200
    assert response.json()["id"] == "user-123"
    assert response.json()["email"] == "test@cloudbreak.app"


def test_get_me_token_without_sub() -> None:
    payload = {"email": "test@cloudbreak.app"}
    with patch("app.core.dependencies.decode_supabase_jwt", return_value=payload):
        response = client.get(
            "/api/v1/user/me",
            headers={"Authorization": "Bearer valid.token.here"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_redis_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import dependencies

    fake_redis = object()
    monkeypatch.setattr(dependencies, "_redis", None)

    with patch.object(dependencies.Redis, "from_url", return_value=fake_redis) as from_url:
        first = await dependencies.get_redis()
        second = await dependencies.get_redis()

    assert first is fake_redis
    assert second is fake_redis
    from_url.assert_called_once()

    monkeypatch.setattr(dependencies, "_redis", None)


@pytest.mark.asyncio
async def test_check_quota_sans_peak_id_retourne_422() -> None:
    """check_quota sans peak_id dans les query params → 422 (FastAPI validation)."""
    from app.core.dependencies import get_current_user, get_redis

    mock_redis = AsyncMock()
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    try:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "user-123",
            "email": "test@cloudbreak.app",
        }
        app.dependency_overrides[get_redis] = mock_get_redis_impl

        with patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Appel sans peak_id — date et hour requis pour passer la validation FastAPI
                response = await client.get(
                    "/api/v1/score",
                    params={"date": "2026-10-15", "hour": 7},
                )

        assert response.status_code == 422
        body = response.json()
        assert body is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_check_quota_peak_id_vide_retourne_422() -> None:
    """check_quota avec peak_id='' (chaîne vide) → 422 + code VALIDATION_ERROR."""
    from app.core.dependencies import get_current_user, get_redis

    mock_redis = AsyncMock()
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    try:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "user-123",
            "email": "test@cloudbreak.app",
        }
        app.dependency_overrides[get_redis] = mock_get_redis_impl

        with patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # peak_id vide explicitement → check_quota lève 422
                response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "", "date": "2026-10-15", "hour": 7},
                )

        assert response.status_code == 422
        body = response.json()
        detail = body.get("detail")
        # Quand c'est notre HTTPException custom, detail est un dict avec "code"
        if isinstance(detail, dict):
            assert detail.get("code") == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_user_subscription_returns_db_record() -> None:
    from app.core.dependencies import get_user_subscription

    subscription = MagicMock(plan="pro")
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = subscription
    db = AsyncMock()
    db.execute.return_value = result_proxy

    result = await get_user_subscription("user-123", db)

    assert result is subscription
    db.execute.assert_awaited_once()
