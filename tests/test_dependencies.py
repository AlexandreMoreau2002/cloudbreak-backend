from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient

from app.main import app


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
    with (
        patch("app.core.dependencies.decode_supabase_jwt", return_value=payload),
        patch(
            "app.api.v1.endpoints.user.get_user_profile",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = client.get(
            "/api/v1/user/me",
            headers={"Authorization": "Bearer valid.token.here"},
        )
    assert response.status_code == 200
    assert response.json()["id"] == "user-123"
    assert response.json()["email"] == "test@cloudbreak.app"


def test_current_user_exposes_anonymous_claim() -> None:
    """Le JWT Supabase anonyme conserve son statut jusqu'aux dépendances métier."""
    from app.core.dependencies import decode_user_payload

    user = decode_user_payload({"sub": "guest", "is_anonymous": True})

    assert user == {
        "id": "guest",
        "email": None,
        "is_anonymous": True,
        "auth_provider": "email",
    }


def test_current_user_defaults_to_permanent_when_claim_is_absent() -> None:
    """Les JWT permanents existants sans claim explicite restent compatibles."""
    from app.core.dependencies import decode_user_payload

    user = decode_user_payload({"sub": "user-123", "email": "test@cloudbreak.app"})

    assert user["is_anonymous"] is False


def test_current_user_reads_provider_from_app_metadata() -> None:
    """Le provider Supabase (ex: apple) est exposé comme auth_provider."""
    from app.core.dependencies import decode_user_payload

    user = decode_user_payload({"sub": "user-123", "app_metadata": {"provider": "apple"}})

    assert user["auth_provider"] == "apple"


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

    with patch.object(
        dependencies.Redis,  # type: ignore[attr-defined]
        "from_url",
        return_value=fake_redis,
    ) as from_url:
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


@pytest.mark.asyncio
async def test_check_quota_bypass_appelle_track_quota_bypassed() -> None:
    from app.core.dependencies import check_quota
    from datetime import UTC, datetime, timedelta

    subscription = MagicMock(plan="premium", expires_at=datetime.now(UTC) + timedelta(days=10))
    db = AsyncMock()
    request = MagicMock()
    request.query_params = {"peak_id": "peak-1"}

    with (
        patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=subscription,
        ),
        patch("app.core.dependencies.track") as mock_track,
    ):
        result = await check_quota(
            request=request, user={"id": "user-123"}, redis=AsyncMock(), db=db
        )

    assert result == {"id": "user-123", "plan": "premium"}
    mock_track.assert_called_once_with("quota_bypassed", "user-123", {"plan": "premium"})


@pytest.mark.asyncio
async def test_check_quota_exceeded_appelle_track_quota_exceeded() -> None:
    from app.core.dependencies import check_quota
    from app.services.quota import QuotaExceededException

    db = AsyncMock()
    request = MagicMock()
    request.query_params = {"peak_id": "peak-1"}

    with (
        patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.core.dependencies.QuotaService.check_and_increment",
            new_callable=AsyncMock,
            side_effect=QuotaExceededException("quota atteint"),
        ),
        patch("app.core.dependencies.track") as mock_track,
    ):
        with pytest.raises(Exception):
            await check_quota(request=request, user={"id": "user-123"}, redis=AsyncMock(), db=db)

    mock_track.assert_called_once_with(
        "quota_exceeded", "user-123", {"peak_id": "peak-1", "plan": "free"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "installation_id",
    [None, "", "not-a-uuid", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
)
async def test_anonymous_quota_rejects_invalid_installation_id_without_redis(
    installation_id: str | None,
) -> None:
    """Un invité sans UUID v4 valide reçoit 400 avant tout accès Redis."""
    from app.core.dependencies import check_quota
    from app.core.errors import ApiError

    request = MagicMock()
    request.query_params = {"peak_id": "peak-1"}
    request.headers = (
        {"X-Cloudbreak-Installation-Id": installation_id} if installation_id is not None else {}
    )
    request.client = MagicMock(host="198.51.100.8")
    redis = AsyncMock()

    with patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(ApiError) as raised:
            await check_quota(
                request=request,
                user={"id": "guest-123", "is_anonymous": True},
                redis=redis,
                db=AsyncMock(),
            )

    assert raised.value.status_code == 400
    assert raised.value.code == "INSTALLATION_ID_INVALID"
    redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_anonymous_quota_runs_rate_installation_then_user_quota() -> None:
    """Le pipeline invité respecte l'ordre IP, installation hachée, puis utilisateur."""
    from datetime import UTC, datetime
    from app.core.dependencies import check_quota

    calls: list[tuple[str, ...]] = []
    request = MagicMock()
    request.query_params = {"peak_id": "peak-1"}
    request.headers = {
        "X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000",
        "X-Forwarded-For": "203.0.113.99",
    }
    request.client = MagicMock(host="198.51.100.8")

    async def record_rate_limit(client_ip: str) -> None:
        calls.append(("rate", client_ip))

    async def record_installation_quota(installation_hash: str, date: str, peak_id: str) -> None:
        calls.append(("installation", installation_hash, date, peak_id))

    async def record_user_quota(user_id: str, date: str, peak_id: str) -> None:
        calls.append(("user", user_id, date, peak_id))

    with (
        patch("app.core.dependencies.datetime") as mock_datetime,
        patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.core.dependencies.RateLimitService.check_anonymous_score",
            new_callable=AsyncMock,
            side_effect=record_rate_limit,
        ),
        patch(
            "app.core.dependencies.QuotaService.check_and_increment_installation",
            new_callable=AsyncMock,
            side_effect=record_installation_quota,
        ),
        patch(
            "app.core.dependencies.QuotaService.check_and_increment",
            new_callable=AsyncMock,
            side_effect=record_user_quota,
        ),
    ):
        mock_datetime.now.return_value = datetime(2026, 9, 28, tzinfo=UTC)
        result = await check_quota(
            request=request,
            user={"id": "guest-123", "is_anonymous": True},
            redis=AsyncMock(),
            db=AsyncMock(),
        )

    assert result["plan"] == "free"
    assert calls == [
        ("rate", "198.51.100.8"),
        (
            "installation",
            "a3a9e1ed9732cab28868127be00f1ce921acaefdd5c3b23a6e9e0072bd9c1a34",
            "2026-09-28",
            "peak-1",
        ),
        ("user", "guest-123", "2026-09-28", "peak-1"),
    ]


@pytest.mark.asyncio
async def test_anonymous_rate_limit_maps_to_stable_429_error() -> None:
    """Le dépassement IP est exposé comme une erreur API stable sans continuer les quotas."""
    from app.core.dependencies import check_quota
    from app.core.errors import ApiError
    from app.services.rate_limit import RateLimitExceededException

    request = MagicMock()
    request.query_params = {"peak_id": "peak-1"}
    request.headers = {"X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000"}
    request.client = MagicMock(host="198.51.100.8")

    with (
        patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.core.dependencies.RateLimitService.check_anonymous_score",
            new_callable=AsyncMock,
            side_effect=RateLimitExceededException("limit reached"),
        ),
        patch(
            "app.core.dependencies.QuotaService.check_and_increment_installation",
            new_callable=AsyncMock,
        ) as installation_quota,
        patch(
            "app.core.dependencies.QuotaService.check_and_increment",
            new_callable=AsyncMock,
        ) as user_quota,
    ):
        with pytest.raises(ApiError) as raised:
            await check_quota(
                request=request,
                user={"id": "guest-123", "is_anonymous": True},
                redis=AsyncMock(),
                db=AsyncMock(),
            )

    assert raised.value.status_code == 429
    assert raised.value.code == "RATE_LIMIT_EXCEEDED"
    installation_quota.assert_not_awaited()
    user_quota.assert_not_awaited()
