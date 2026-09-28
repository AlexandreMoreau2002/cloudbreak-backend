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

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_redis
from app.domain.weather_types import PressureLevelData, WeatherData


def _make_mock_redis() -> AsyncMock:
    """Mock Redis dont EVAL renvoie une décision quota réaliste par défaut."""
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 1
    return mock_redis


class _StatefulRedis:
    """Double Redis minimal qui exécute les contrats des deux scripts Lua."""

    def __init__(self) -> None:
        self._rate_counts: dict[str, int] = {}
        self._quota_sets: dict[str, set[str]] = {}
        self.eval = AsyncMock(side_effect=self._eval)

    async def _eval(self, script: str, key_count: int, key: str, *args: str) -> int:
        del script, key_count
        if key.startswith("rate_limit:anonymous_score:"):
            count = self._rate_counts.get(key, 0) + 1
            self._rate_counts[key] = count
            return count

        peak_id, limit, _ttl = args
        unlocked = self._quota_sets.setdefault(key, set())
        if peak_id in unlocked:
            return 0
        if len(unlocked) >= int(limit):
            return -1
        unlocked.add(peak_id)
        return 1


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}
MOCK_ANONYMOUS_USER = {"id": "guest-123", "email": None, "is_anonymous": True}
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
def auth_anonymous() -> object:
    """Auth override pour un invité Supabase."""
    from app.core.dependencies import get_current_user

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: MOCK_ANONYMOUS_USER
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

    # Script Lua : nouveau sommet autorisé.
    mock_redis = _make_mock_redis()

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
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_anonymous_user_can_get_a_score_with_quota(auth_anonymous: object) -> None:
    """Le quota et le score restent disponibles pour une session invitée."""
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
                    headers={
                        "X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000"
                    },
                )
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    assert mock_redis.eval.await_count == 3


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

    # Script Lua : sommet différent refusé à la limite quotidienne.
    mock_redis = _make_mock_redis()
    mock_redis.eval.return_value = -1

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
    mock_redis.eval.assert_awaited_once()


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
    mock_subscription.expires_at = datetime(2099, 1, 1, tzinfo=UTC)  # Loin dans le futur

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
    mock_subscription.expires_at = datetime(2099, 1, 1, tzinfo=UTC)  # Loin dans le futur

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
    mock_subscription.expires_at = datetime(2026, 1, 1, tzinfo=UTC)  # Déjà expiré

    patch_subscription = patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=mock_subscription,
    )

    # 1er appel : le script Lua autorise le sommet.
    mock_redis_first = _make_mock_redis()

    # 2ème appel : le script Lua refuse le nouveau sommet.
    mock_redis_second = _make_mock_redis()
    mock_redis_second.eval.return_value = -1

    call_count = 0

    async def mock_get_redis_stateful() -> AsyncMock:
        nonlocal call_count
        call_count += 1
        return mock_redis_first if call_count == 1 else mock_redis_second

    app.dependency_overrides[get_redis] = mock_get_redis_stateful

    try:
        with patch_peak, patch_weather, patch_subscription:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # 1er appel → 200 OK (quota pas encore atteint)
                response_first = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                )
                # 2ème appel → 429 (quota freemium épuisé)
                response_second = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 8},
                )
    finally:
        if get_redis in app.dependency_overrides:
            del app.dependency_overrides[get_redis]

    # Avec abonnement expiré → freemium quota s'applique
    assert response_first.status_code == 200
    assert response_second.status_code == 429
    assert response_second.json()["detail"]["code"] == "QUOTA_EXCEEDED"
    mock_redis_first.eval.assert_awaited_once()
    mock_redis_second.eval.assert_awaited_once()


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
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "installation_id",
    [None, "", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
)
async def test_anonymous_score_rejects_missing_empty_or_non_v4_installation_id(
    auth_anonymous: object,
    installation_id: str | None,
) -> None:
    """Le contrat HTTP refuse l'installation invalide avant Redis."""
    mock_redis = _make_mock_redis()

    async def mock_get_redis_impl() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_redis] = mock_get_redis_impl
    headers = (
        {"X-Cloudbreak-Installation-Id": installation_id} if installation_id is not None else {}
    )
    try:
        with patch(
            "app.core.dependencies.get_user_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                    headers=headers,
                )
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 400
    assert response.json()["code"] == "INSTALLATION_ID_INVALID"
    mock_redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_installation_blocks_a_new_peak_after_guest_rotation() -> None:
    """Créer une autre session Supabase ne réinitialise pas le quota installation."""
    from app.core.dependencies import get_current_user

    user_state = {"current": {"id": "guest-a", "is_anonymous": True}}
    redis = _StatefulRedis()

    async def mock_get_redis_impl() -> _StatefulRedis:
        return redis

    app.dependency_overrides[get_current_user] = lambda: user_state["current"]
    app.dependency_overrides[get_redis] = mock_get_redis_impl
    try:
        with (
            patch(
                "app.core.dependencies.get_user_subscription",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.v1.endpoints.score.get_peak_by_id",
                new_callable=AsyncMock,
                return_value=MOCK_PEAK,
            ),
            patch(
                "app.api.v1.endpoints.score.weather_service.get_forecast",
                new_callable=AsyncMock,
                return_value=MOCK_WEATHER,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000"}
                first = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                    headers=headers,
                )
                user_state["current"] = {"id": "guest-b", "is_anonymous": True}
                second = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-2", "date": "2026-04-01", "hour": 7},
                    headers=headers,
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_redis, None)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_same_anonymous_peak_at_another_hour_remains_allowed() -> None:
    """Le même sommet reste déverrouillé pour toutes ses heures."""
    from app.core.dependencies import get_current_user

    redis = _StatefulRedis()

    async def mock_get_redis_impl() -> _StatefulRedis:
        return redis

    app.dependency_overrides[get_current_user] = lambda: MOCK_ANONYMOUS_USER
    app.dependency_overrides[get_redis] = mock_get_redis_impl
    try:
        with (
            patch(
                "app.core.dependencies.get_user_subscription",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.v1.endpoints.score.get_peak_by_id",
                new_callable=AsyncMock,
                return_value=MOCK_PEAK,
            ),
            patch(
                "app.api.v1.endpoints.score.weather_service.get_forecast",
                new_callable=AsyncMock,
                return_value=MOCK_WEATHER,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000"}
                first = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                    headers=headers,
                )
                second = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 8},
                    headers=headers,
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_redis, None)

    assert first.status_code == 200
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_score_rate_limit_allows_60_then_rejects_61st() -> None:
    """L'IP issue de Request.client obtient exactement 60 scores par fenêtre."""
    from app.core.dependencies import get_current_user

    redis = _StatefulRedis()
    db = AsyncMock()
    db.add = MagicMock()

    async def mock_get_redis_impl() -> _StatefulRedis:
        return redis

    app.dependency_overrides[get_current_user] = lambda: MOCK_ANONYMOUS_USER
    app.dependency_overrides[get_redis] = mock_get_redis_impl
    app.dependency_overrides[get_db] = lambda: db
    try:
        with (
            patch(
                "app.core.dependencies.get_user_subscription",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.v1.endpoints.score.get_peak_by_id",
                new_callable=AsyncMock,
                return_value=MOCK_PEAK,
            ),
            patch(
                "app.api.v1.endpoints.score.weather_service.get_forecast",
                new_callable=AsyncMock,
                return_value=MOCK_WEATHER,
            ),
        ):
            transport = ASGITransport(app=app, client=("198.51.100.8", 123))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = {"X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000"}
                for _ in range(60):
                    accepted = await client.get(
                        "/api/v1/score",
                        params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                        headers=headers,
                    )
                    assert accepted.status_code == 200

                rejected = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-04-01", "hour": 7},
                    headers=headers,
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_db, None)

    assert rejected.status_code == 429
    assert rejected.json()["code"] == "RATE_LIMIT_EXCEEDED"
