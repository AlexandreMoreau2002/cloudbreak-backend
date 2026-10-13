"""
Tests de l'endpoint GET /api/v1/score

Flux testé :
  JWT valide → peak trouvé en DB → météo (cache ou provider) → algo score → réponse JSON

On mocke :
- L'authentification JWT (get_current_user)
- La DB (peak lookup)
- Le service météo (WeatherService)
Pour tester uniquement la logique de l'endpoint lui-même.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.dependencies import get_current_user, get_redis
from app.db.session import get_db
from app.domain.weather_types import PressureLevelData, WeatherData


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}

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

WEEK_HOURS = (6, 8, 10, 12, 14, 16, 18, 20, 22)
WEEK_START_DATE = datetime.now(UTC).date()
MOCK_WEEK = {
    (WEEK_START_DATE + timedelta(days=offset)).isoformat(): {
        hour: MOCK_WEATHER for hour in WEEK_HOURS
    }
    for offset in range(7)
}


@pytest.fixture
def auth_override():
    from app.core.dependencies import get_current_user

    # Mock Redis (quota check)
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 1

    async def mock_get_redis_impl():
        return mock_redis

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_redis] = mock_get_redis_impl

    # Patch get_user_subscription au niveau module (appel direct, pas Depends)
    with patch(
        "app.core.dependencies.get_user_subscription",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield mock_redis

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_score_retourne_200_avec_jwt_valide(auth_override: None) -> None:
    """Un JWT valide + peak existant → réponse 200 avec tous les champs."""
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
    with patch_peak, patch_weather:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score",
                params={"peak_id": "peak-1", "date": "2026-10-15", "hour": 7},
            )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "verdict" in data
    assert "label_code" in data
    assert "context_code" in data
    assert "context_params" in data
    assert "cloud_base" in data
    assert "peak_slug" in data
    assert "peak_region" in data
    assert "optimal_window_start" in data
    assert "optimal_window_end" in data
    assert "sunrise" in data
    assert "stability_hours" in data
    assert "conditions" in data
    assert "cloud_layer_viz" in data
    assert data["verdict"] in ("none", "high", "medium", "low")
    assert 0 <= data["score"] <= 100
    assert data["label_code"]
    assert data["context_code"]
    assert data["peak_slug"] == "mont-blanc"
    assert data["peak_region"] == "Massif du Mont-Blanc"
    assert data["label_code"] == "score.label.high"
    assert data["context_code"] == "score.context.high.stable_window"
    assert data["context_params"] == {"cloud_base_gap_m": 700}
    assert data["optimal_window_start"]
    assert data["optimal_window_end"]
    assert data["sunrise"]
    assert isinstance(data["stability_hours"], int)
    assert data["conditions"]["cloud_base_m"] == 800
    assert data["conditions"]["humidity_pct"] == 85.0
    assert data["conditions"]["wind_speed_kmh"] == 8.0
    assert data["conditions"]["pressure_hpa"] == 1015.0
    assert data["conditions"]["cloud_cover_low_pct"] == 55.0
    assert data["cloud_layer_viz"]["summit_altitude"] == 1500
    assert data["cloud_layer_viz"]["cloud_base"] == 800
    assert len(data["cloud_layer_viz"]["pressure_levels"]) == 2


@pytest.mark.asyncio
async def test_score_sans_jwt_retourne_401() -> None:
    """Sans header Authorization → 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/score",
            params={"peak_id": "peak-1", "date": "2026-10-15", "hour": 7},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_score_peak_introuvable_retourne_404(auth_override: None) -> None:
    """Peak inexistant → 404 avec code PEAK_NOT_FOUND."""
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=None,
    )
    with patch_peak:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score",
                params={"peak_id": "inexistant", "date": "2026-10-15", "hour": 7},
            )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PEAK_NOT_FOUND"


@pytest.mark.asyncio
async def test_score_meteo_indisponible_retourne_503(auth_override: None) -> None:
    """Provider météo down → 503 avec code WEATHER_UNAVAILABLE."""
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_forecast",
        new_callable=AsyncMock,
        side_effect=Exception("timeout"),
    )
    with patch_peak, patch_weather:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score",
                params={"peak_id": "peak-1", "date": "2026-10-15", "hour": 7},
            )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "WEATHER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_score_param_date_manquant_retourne_422(auth_override: None) -> None:
    """Paramètre date absent → 422 Unprocessable Entity."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/score",
            params={"peak_id": "peak-1", "hour": 7},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_peak_by_id_retourne_peak() -> None:
    """get_peak_by_id retourne le peak si trouvé."""
    from app.api.v1.endpoints.score import get_peak_by_id

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MOCK_PEAK
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_peak_by_id("peak-1", mock_db)
    assert result == MOCK_PEAK


@pytest.mark.asyncio
async def test_get_peak_by_id_retourne_none_si_absent() -> None:
    """get_peak_by_id retourne None si le peak n'existe pas."""
    from app.api.v1.endpoints.score import get_peak_by_id

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_peak_by_id("inexistant", mock_db)
    assert result is None


@pytest.mark.asyncio
async def test_get_score_appelle_track_score_calculated(auth_override: None) -> None:
    """L'endpoint appelle track('score_calculated', ...) avec les bonnes propriétés."""
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
    patch_track = patch("app.api.v1.endpoints.score.track")
    with patch_peak, patch_weather, patch_track as mock_track:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score",
                params={"peak_id": "peak-1", "date": "2026-10-15", "hour": 6},
            )

    assert response.status_code == 200
    mock_track.assert_called_once()
    call_args = mock_track.call_args
    assert call_args[0][0] == "score_calculated"
    assert call_args[0][1] == MOCK_USER["id"]
    properties = call_args[0][2]
    assert properties["peak_id"] == "peak-1"
    assert "verdict" in properties
    assert "score" in properties
    assert properties["plan"] == "free"


@pytest.mark.asyncio
async def test_get_score_persiste_une_prediction_et_expose_son_id(auth_override: None) -> None:
    """GET /api/v1/score écrit une ligne Prediction et renvoie prediction_id."""
    from app.db.session import get_db

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda pred: setattr(pred, "id", "pred-uuid-1"))

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

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch_peak, patch_weather:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/score", params={"peak_id": "peak-1", "date": "2026-07-24", "hour": 6}
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["prediction_id"] == "pred-uuid-1"
    assert mock_db.add.called
    assert mock_db.commit.await_count >= 1


@pytest.mark.asyncio
async def test_score_week_returns_seven_days_and_nine_hours(auth_override: AsyncMock) -> None:
    mock_db = AsyncMock()
    mock_db.add_all = MagicMock()
    mock_db.commit = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_week_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEEK,
    )

    try:
        with patch_peak, patch_weather:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/score/week",
                    params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    by_date = response.json()["by_date"]
    assert len(by_date) == 7
    assert set(by_date[WEEK_START_DATE.isoformat()]) == {str(hour) for hour in WEEK_HOURS}
    assert auth_override.eval.await_count == 2
    persisted_ids = {str(prediction.id) for prediction in mock_db.add_all.call_args.args[0]}
    response_ids = {
        score["prediction_id"] for by_hour in by_date.values() for score in by_hour.values()
    }
    assert response_ids == persisted_ids


@pytest.mark.asyncio
async def test_score_week_rejects_malformed_start_date(auth_override: AsyncMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/score/week",
            params={"peak_id": "peak-1", "start_date": "not-a-date"},
        )

    assert response.status_code == 422
    auth_override.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_score_week_rejects_start_date_outside_ui_window_without_redis(
    auth_override: AsyncMock,
) -> None:
    outside_ui_window = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/score/week",
            params={"peak_id": "peak-1", "start_date": outside_ui_window},
        )

    assert response.status_code == 422
    auth_override.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_score_week_returns_peak_not_found(auth_override: AsyncMock) -> None:
    with patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score/week",
                params={"peak_id": "missing", "start_date": WEEK_START_DATE.isoformat()},
            )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PEAK_NOT_FOUND"
    auth_override.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_score_week_returns_weather_unavailable(auth_override: AsyncMock) -> None:
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_week_forecast",
        new_callable=AsyncMock,
        side_effect=Exception("timeout"),
    )

    with patch_peak, patch_weather:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score/week",
                params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
            )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "WEATHER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_score_week_returns_generated_prediction_ids_if_persistence_fails(
    auth_override: AsyncMock,
) -> None:
    mock_db = AsyncMock()
    mock_db.add_all = MagicMock()
    mock_db.commit = AsyncMock(side_effect=Exception("database unavailable"))
    mock_db.rollback = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    patch_peak = patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    )
    patch_weather = patch(
        "app.api.v1.endpoints.score.weather_service.get_week_forecast",
        new_callable=AsyncMock,
        return_value=MOCK_WEEK,
    )

    try:
        with patch_peak, patch_weather:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/score/week",
                    params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert mock_db.add_all.call_count == 1
    assert mock_db.commit.await_count == 1
    assert mock_db.rollback.await_count == 1
    prediction_ids = [
        score["prediction_id"]
        for by_hour in response.json()["by_date"].values()
        for score in by_hour.values()
    ]
    assert len(prediction_ids) == 63
    assert len(set(prediction_ids)) == 63


@pytest.mark.asyncio
async def test_score_week_preserves_quota_exceeded_code(auth_override: AsyncMock) -> None:
    auth_override.eval.side_effect = [1, -1]

    with patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score/week",
                params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
            )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "QUOTA_EXCEEDED"
    assert auth_override.eval.await_count == 2


@pytest.mark.asyncio
async def test_score_week_rate_limit_preserves_error_code(auth_override: AsyncMock) -> None:
    auth_override.eval.return_value = 13

    with patch(
        "app.api.v1.endpoints.score.get_peak_by_id",
        new_callable=AsyncMock,
        return_value=MOCK_PEAK,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/score/week",
                params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
            )

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"
    auth_override.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_week_preserves_rate_limit_exceeded_code() -> None:
    anonymous_user = {"id": "guest-123", "email": None, "is_anonymous": True}
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 61

    async def get_mock_redis() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_current_user] = lambda: anonymous_user
    app.dependency_overrides[get_redis] = get_mock_redis
    try:
        with patch(
            "app.api.v1.endpoints.score.get_peak_by_id",
            new_callable=AsyncMock,
            return_value=MOCK_PEAK,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/score/week",
                    params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
                    headers={
                        "X-Cloudbreak-Installation-Id": "550e8400-e29b-41d4-a716-446655440000"
                    },
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_week_rate_limit_also_applies_to_premium_user() -> None:
    premium_user = {"id": "premium-123", "email": "premium@test.com"}
    subscription = MagicMock(
        plan="premium",
        status="active",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 13

    async def get_mock_redis() -> AsyncMock:
        return mock_redis

    app.dependency_overrides[get_current_user] = lambda: premium_user
    app.dependency_overrides[get_redis] = get_mock_redis
    try:
        with (
            patch(
                "app.api.v1.endpoints.score.get_peak_by_id",
                new_callable=AsyncMock,
                return_value=MOCK_PEAK,
            ),
            patch(
                "app.core.dependencies.get_user_subscription",
                new_callable=AsyncMock,
                return_value=subscription,
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/score/week",
                    params={"peak_id": "peak-1", "start_date": WEEK_START_DATE.isoformat()},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"
    mock_redis.eval.assert_awaited_once()
