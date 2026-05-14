"""
Tests du flux complet quota — endpoint /api/v1/score avec vérification quota.

Cas testés:
  1. Freemium 1er appel → 200 OK + score retourné
  2. Freemium 2e appel → 429 QUOTA_EXCEEDED
  3. Premium illimité → 5+ appels OK
  4. Pro illimité → 5+ appels OK
  5. Abonnement expiré → fallback freemium
  6. Pas de record subscription → freemium
"""

import pytest
from app.main import app
from contextlib import asynccontextmanager
from app.core.dependencies import get_redis
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from app.domain.weather_types import PressureLevelData, WeatherData


def _make_mock_redis() -> AsyncMock:
    """Mock Redis avec pipeline() correctement configuré comme async context manager."""
    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()

    @asynccontextmanager
    async def mock_pipeline() -> object:
        yield mock_pipe

    mock_redis.pipeline = mock_pipeline
    return mock_redis


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}
MOCK_PREMIUM_USER = {"id": "user-premium", "email": "premium@test.com"}
MOCK_PRO_USER = {"id": "user-pro", "email": "pro@test.com"}

MOCK_PEAK = MagicMock()
MOCK_PEAK.id = "peak-1"
MOCK_PEAK.name = "Mont Blanc"
MOCK_PEAK.slug = "mont-blanc"
MOCK_PEAK.lat = 45.83
MOCK_PEAK.lng = 6.86
MOCK_PEAK.altitude = 1500
MOCK_PEAK.region = "Massif du Mont-Blanc"

MOCK_WEATHER = WeatherData(
    cloud_base=800,
    humidity=85.0,
    wind_speed=8.0,
    temperature_2m=4.0,
    temperature_850hpa=9.0,
    temperature_925hpa=5.0,
    pressure=1015.0,
    cloud_cover_low=55.0,
    month=10,
    pressure_levels=[
        PressureLevelData(
            pressure_hpa=925,
            altitude_m=800,
            temperature_c=5.0,
            relative_humidity=90.0,
            dew_point_spread=1.0,
        ),
        PressureLevelData(
            pressure_hpa=850,
            altitude_m=1500,
            temperature_c=9.0,
            relative_humidity=80.0,
            dew_point_spread=2.0,
        ),
    ],
)


@pytest.fixture
def auth_freemium() -> object:
    """Auth override pour user freemium."""
    from app.core.dependencies import get_current_user

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    yield
    if original is not None:
        app.dependency_overrides[get_current_user] = original
    elif get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture
def auth_premium() -> object:
    """Auth override pour user Premium."""
    from app.core.dependencies import get_current_user

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: MOCK_PREMIUM_USER
    yield
    if original is not None:
        app.dependency_overrides[get_current_user] = original
    elif get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture
def auth_pro() -> object:
    """Auth override pour user Pro."""
    from app.core.dependencies import get_current_user

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: MOCK_PRO_USER
    yield
    if original is not None:
        app.dependency_overrides[get_current_user] = original
    elif get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.mark.asyncio
async def test_quota_score_endpoint_first_call_returns_200(auth_freemium: object) -> None:
    """Freemium 1er appel → 200 OK + score retourné."""
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEATHER,
    )
    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=None,
    )

    # Mock Redis avec quota absent (1er check — sommet pas encore déverrouillé)
    mock_redis = _make_mock_redis()
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    # Override dependencies
    app.dependency_overrides[get_redis] = mock_get_redis_impl

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                )
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]

    assert response.status_code == 200
    data = response.json()
    assert data["score"]
    assert data["verdict"] in ("none", "high", "medium", "low")


@pytest.mark.asyncio
async def test_quota_score_endpoint_second_call_returns_429(auth_freemium: object) -> None:
    """Freemium 2e appel → 429 QUOTA_EXCEEDED."""
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEATHER,
    )
    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=None,
    )

    # Mock Redis avec quota déjà atteint (sommet différent, scard=1 = limite)
    mock_redis = _make_mock_redis()
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 1  # 1 sommet déjà déverrouillé = limite atteinte

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_redis] = mock_get_redis_impl

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                )
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]

    assert response.status_code == 429
    data = response.json()
    assert data["detail"]["code"] == "QUOTA_EXCEEDED"
    assert "quota journalier" in data["detail"]["detail"].lower()


@pytest.mark.asyncio
async def test_quota_premium_user_unlimited_calls(auth_premium: object) -> None:
    """Premium user → appels illimités (bypass quota)."""
    from datetime import datetime

    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEATHER,
    )

    # Mock subscription avec plan "premium" et expiry future
    mock_subscription = MagicMock()
    mock_subscription.plan = "premium"
    mock_subscription.expires_at = datetime(2099, 1, 1)  # Loin dans le futur

    # Patch get_user_subscription au niveau du module dependencies
    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=mock_subscription,
    )

    # Mock Redis
    mock_redis = AsyncMock()

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_redis] = mock_get_redis_impl

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # 1er appel
                response1 = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                )
                # 2e appel
                response2 = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 8},
                )
                # 3e appel
                response3 = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 9},
                )
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response3.status_code == 200


@pytest.mark.asyncio
async def test_quota_pro_user_unlimited_calls(auth_pro: object) -> None:
    """Pro user → appels illimités (bypass quota)."""
    from datetime import datetime

    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEATHER,
    )

    # Mock subscription avec plan "pro" et expiry future
    mock_subscription = MagicMock()
    mock_subscription.plan = "pro"
    mock_subscription.expires_at = datetime(2099, 1, 1)  # Loin dans le futur

    # Patch get_user_subscription au niveau du module dependencies
    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=mock_subscription,
    )

    # Mock Redis
    mock_redis = AsyncMock()

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_redis] = mock_get_redis_impl

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Plusieurs appels → tous OK
                for hour in range(6, 10):
                    response = await client.get(
                        "/api/v1/score",
                        params={"peak_id": "peak-1", "date": "2026-04-01", "hour": hour},
                    )
                    assert response.status_code == 200
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]


@pytest.mark.asyncio
async def test_quota_expired_subscription_falls_back_to_freemium(
    auth_freemium: object,
) -> None:
    """Abonnement expiré → fallback freemium (quota actif)."""
    from datetime import datetime

    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEATHER,
    )

    # Mock subscription expiré
    mock_subscription = MagicMock()
    mock_subscription.plan = "premium"
    mock_subscription.expires_at = datetime(2026, 1, 1)  # Déjà expiré

    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=mock_subscription,
    )

    mock_redis = _make_mock_redis()
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_redis] = mock_get_redis_impl

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                )
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]

    # Avec abonnement expiré → freemium quota s'applique
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_quota_no_subscription_record_is_freemium(auth_freemium: object) -> None:
    """Pas de record subscription → user est freemium (quota actif)."""
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEATHER,
    )
    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=None,
    )

    mock_redis = _make_mock_redis()
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_redis] = mock_get_redis_impl

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                )
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]

    assert response.status_code == 200
