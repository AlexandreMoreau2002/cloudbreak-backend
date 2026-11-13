"""
Test de feature — flux complet Validation Terrain (story 6.1).

Flux testé :
  GET /api/v1/score (persiste une Prediction, renvoie prediction_id)
  → POST /api/v1/validations (référence ce prediction_id)
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from datetime import UTC, datetime

from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_redis, get_current_user
from app.domain.weather_types import PressureLevelData, WeatherData

MOCK_VALIDATED_AT = datetime(2026, 7, 24, 10, 0, 0, tzinfo=UTC)


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}
KNOWN_PREDICTION_ID = "11111111-1111-4111-8111-111111111111"

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


@pytest.mark.asyncio
async def test_feature_score_puis_validation_terrain() -> None:
    """GET /api/v1/score persiste une Prediction → POST /api/v1/validations la référence."""
    # --- Phase 1 : GET /api/v1/score ---
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.incr.return_value = 1

    async def mock_get_redis_impl():
        return mock_redis

    score_db = AsyncMock()
    score_db.add = MagicMock()
    score_db.commit = AsyncMock()
    score_db.refresh = AsyncMock(side_effect=lambda pred: setattr(pred, "id", KNOWN_PREDICTION_ID))

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_redis] = mock_get_redis_impl
    app.dependency_overrides[get_db] = lambda: score_db

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

    try:
        with patch_peak, patch_weather, patch_subscription:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                score_response = await client.get(
                    "/api/v1/score",
                    params={"peak_id": "peak-1", "date": "2026-07-24", "hour": 6},
                )
    finally:
        app.dependency_overrides.clear()

    assert score_response.status_code == 200
    score_body = score_response.json()
    prediction_id = score_body["prediction_id"]
    assert prediction_id == KNOWN_PREDICTION_ID

    # --- Phase 2 : POST /api/v1/validations ---
    mock_prediction = MagicMock()
    mock_prediction.id = prediction_id

    validation_db = AsyncMock()
    validation_db.add = MagicMock()
    validation_db.commit = AsyncMock()
    pred_result = MagicMock()
    pred_result.scalar_one_or_none.return_value = mock_prediction
    validation_db.execute = AsyncMock(return_value=pred_result)
    validation_db.refresh = AsyncMock(
        side_effect=lambda v: (
            setattr(v, "id", "validation-uuid-1") or setattr(v, "validated_at", MOCK_VALIDATED_AT)
        )
    )

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_db] = lambda: validation_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            validation_response = await client.post(
                "/api/v1/validations",
                json={
                    "prediction_id": prediction_id,
                    "result": True,
                    "lat": 45.83,
                    "lng": 6.86,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert validation_response.status_code == 201
    validation_body = validation_response.json()
    assert validation_body["prediction_id"] == prediction_id
