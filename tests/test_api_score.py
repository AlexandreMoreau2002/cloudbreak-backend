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

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.domain.weather_types import WeatherData


MOCK_USER = {"id": "user-123", "email": "alex@test.com"}

MOCK_PEAK = MagicMock()
MOCK_PEAK.id = "peak-1"
MOCK_PEAK.name = "Mont Blanc"
MOCK_PEAK.slug = "mont-blanc"
MOCK_PEAK.lat = 45.83
MOCK_PEAK.lng = 6.86
MOCK_PEAK.altitude = 1500

MOCK_WEATHER = WeatherData(
    cloud_base=800,
    humidity=85.0,
    wind_speed=8.0,
    temperature_2m=4.0,
    temperature_850hpa=9.0,
    temperature_925hpa=5.0,
    pressure=1015.0,
    cloud_cover_low=50.0,
    month=10,
)


@pytest.fixture
def auth_override():
    from app.core.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    yield
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
    assert "cloud_base" in data
    assert "conditions" in data
    assert data["verdict"] in ("none", "high", "medium", "low")
    assert 0 <= data["score"] <= 100


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
