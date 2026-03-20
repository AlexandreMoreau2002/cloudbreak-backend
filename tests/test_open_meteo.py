"""
Tests du provider Open-Meteo.

Couvre :
- _estimate_cloud_base_skewt : détection Skew-T (RH + dew point spread)
- OpenMeteoProvider.get_forecast : appel HTTP mocké → WeatherData normalisé
- Paramètre hour : index dans les données horaires
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.weather_providers.base import PressureLevelData

from app.services.weather_providers.open_meteo import (
    OpenMeteoProvider,
    _estimate_cloud_base_skewt,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_level(
    pressure_hpa: int,
    altitude_m: int,
    relative_humidity: float,
    dew_point_spread: float,
    temperature_c: float = 5.0,
) -> PressureLevelData:
    return PressureLevelData(
        pressure_hpa=pressure_hpa,
        altitude_m=altitude_m,
        temperature_c=temperature_c,
        relative_humidity=relative_humidity,
        dew_point_spread=dew_point_spread,
    )


# ── _estimate_cloud_base_skewt ────────────────────────────────────────────────


class TestEstimateCloudBaseSkewt:
    """
    Méthode Skew-T : premier niveau (bottom-up) où RH >= 88% ET T-Td < 2°C.
    """

    def test_ciel_clair_retourne_5000(self) -> None:
        """Aucun niveau ne satisfait les critères → ciel clair → 5000m."""
        levels = [
            make_level(925, 800, relative_humidity=70.0, dew_point_spread=5.0),
            make_level(850, 1500, relative_humidity=60.0, dew_point_spread=6.0),
            make_level(800, 1950, relative_humidity=50.0, dew_point_spread=8.0),
            make_level(700, 3000, relative_humidity=40.0, dew_point_spread=10.0),
        ]
        assert _estimate_cloud_base_skewt(levels) == 5000

    def test_nuage_bas_925hpa(self) -> None:
        """RH >= 88% ET T-Td < 2°C à 925 hPa → base = altitude de ce niveau."""
        levels = [
            make_level(925, 800, relative_humidity=92.0, dew_point_spread=1.0),
            make_level(850, 1500, relative_humidity=60.0, dew_point_spread=5.0),
            make_level(800, 1950, relative_humidity=50.0, dew_point_spread=8.0),
            make_level(700, 3000, relative_humidity=40.0, dew_point_spread=10.0),
        ]
        assert _estimate_cloud_base_skewt(levels) == 800

    def test_nuage_moyen_850hpa(self) -> None:
        """Pas de nuage à 925hPa mais saturation à 850hPa → base à altitude 850hPa."""
        levels = [
            make_level(925, 800, relative_humidity=70.0, dew_point_spread=5.0),
            make_level(850, 1500, relative_humidity=90.0, dew_point_spread=1.5),
            make_level(800, 1950, relative_humidity=50.0, dew_point_spread=8.0),
            make_level(700, 3000, relative_humidity=40.0, dew_point_spread=10.0),
        ]
        assert _estimate_cloud_base_skewt(levels) == 1500

    def test_scan_bottom_up_retourne_le_plus_bas(self) -> None:
        """Si plusieurs niveaux satisfont, retourne le plus bas."""
        levels = [
            make_level(925, 800, relative_humidity=92.0, dew_point_spread=1.0),
            make_level(850, 1500, relative_humidity=91.0, dew_point_spread=1.0),
            make_level(800, 1950, relative_humidity=50.0, dew_point_spread=8.0),
            make_level(700, 3000, relative_humidity=40.0, dew_point_spread=10.0),
        ]
        assert _estimate_cloud_base_skewt(levels) == 800

    def test_rh_suffisant_mais_spread_trop_grand(self) -> None:
        """RH élevé mais T-Td >= 2°C → pas saturé → ciel clair."""
        levels = [
            make_level(925, 800, relative_humidity=90.0, dew_point_spread=3.0),
            make_level(850, 1500, relative_humidity=89.0, dew_point_spread=2.5),
            make_level(800, 1950, relative_humidity=50.0, dew_point_spread=8.0),
            make_level(700, 3000, relative_humidity=40.0, dew_point_spread=10.0),
        ]
        assert _estimate_cloud_base_skewt(levels) == 5000

    def test_spread_ok_mais_rh_insuffisant(self) -> None:
        """T-Td < 2°C mais RH < 88% → pas de nuage."""
        levels = [
            make_level(925, 800, relative_humidity=85.0, dew_point_spread=1.0),
            make_level(850, 1500, relative_humidity=80.0, dew_point_spread=1.5),
            make_level(800, 1950, relative_humidity=50.0, dew_point_spread=0.5),
            make_level(700, 3000, relative_humidity=40.0, dew_point_spread=0.3),
        ]
        assert _estimate_cloud_base_skewt(levels) == 5000


# ── OpenMeteoProvider ─────────────────────────────────────────────────────────


def _make_mock_response(hourly: dict) -> MagicMock:
    """Crée un mock de réponse httpx."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"hourly": hourly}
    return mock_response


def _make_hourly(
    humidity_2m: float = 75.0,
    wind_speed: float = 10.0,
    pressure: float = 1013.0,
    temp_2m: float = 6.0,
    temp_925: float = 5.0,
    temp_850: float = 8.0,
    cloud_cover_low: float = 30.0,
    # Par niveau : (rh, geo_height, dew_point)
    level_925: tuple = (70.0, 800, 4.0),
    level_850: tuple = (65.0, 1500, 3.0),
    level_800: tuple = (55.0, 1950, 1.0),
    level_700: tuple = (45.0, 3000, 0.5),
) -> dict:
    """Construit un dict hourly Open-Meteo minimal avec 24 valeurs."""
    hourly: dict = {
        "relative_humidity_2m": [humidity_2m] * 24,
        "wind_speed_10m": [wind_speed] * 24,
        "surface_pressure": [pressure] * 24,
        "temperature_2m": [temp_2m] * 24,
        "cloud_cover_low": [cloud_cover_low] * 24,
        "temperature_925hPa": [temp_925] * 24,
        "temperature_850hPa": [temp_850] * 24,
        "temperature_800hPa": [temp_850 - 1] * 24,
        "temperature_700hPa": [temp_850 - 3] * 24,
        "relative_humidity_925hPa": [level_925[0]] * 24,
        "relative_humidity_850hPa": [level_850[0]] * 24,
        "relative_humidity_800hPa": [level_800[0]] * 24,
        "relative_humidity_700hPa": [level_700[0]] * 24,
        "geopotential_height_925hPa": [level_925[1]] * 24,
        "geopotential_height_850hPa": [level_850[1]] * 24,
        "geopotential_height_800hPa": [level_800[1]] * 24,
        "geopotential_height_700hPa": [level_700[1]] * 24,
        "dew_point_925hPa": [temp_925 - level_925[2]] * 24,
        "dew_point_850hPa": [temp_850 - level_850[2]] * 24,
        "dew_point_800hPa": [(temp_850 - 1) - level_800[2]] * 24,
        "dew_point_700hPa": [(temp_850 - 3) - level_700[2]] * 24,
    }
    return hourly


@pytest.mark.asyncio
async def test_get_forecast_retourne_weather_data() -> None:
    """get_forecast retourne un WeatherData bien construit."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_make_mock_response(_make_hourly()))

    provider = OpenMeteoProvider(client=mock_client)
    result = await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15")

    assert result.month == 10
    assert 0 < result.cloud_base <= 5000
    assert 0.0 <= result.humidity <= 100.0
    assert result.wind_speed >= 0.0
    assert len(result.pressure_levels) == 4


@pytest.mark.asyncio
async def test_get_forecast_appelle_la_bonne_url() -> None:
    """get_forecast appelle bien l'URL Open-Meteo."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_make_mock_response(_make_hourly()))

    provider = OpenMeteoProvider(client=mock_client)
    await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15")

    call_args = mock_client.get.call_args
    assert "open-meteo.com" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_forecast_temperature_inversion() -> None:
    """temperature_850hpa est T@850hPa, temperature_925hpa est T@925hPa."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        return_value=_make_mock_response(_make_hourly(temp_2m=3.0, temp_850=9.0, temp_925=4.0))
    )

    provider = OpenMeteoProvider(client=mock_client)
    result = await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15")

    assert result.temperature_2m == pytest.approx(3.0)
    assert result.temperature_850hpa == pytest.approx(9.0)
    assert result.temperature_925hpa == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_get_forecast_respecte_parametre_hour() -> None:
    """Le paramètre hour détermine l'index dans les données horaires."""
    # Données différentes selon l'heure : index 9 = 30.0, index 6 = 10.0
    wind_data = [10.0] * 24
    wind_data[9] = 30.0

    hourly = _make_hourly(wind_speed=10.0)
    hourly["wind_speed_10m"] = wind_data

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_make_mock_response(hourly))

    provider = OpenMeteoProvider(client=mock_client)
    result_h6 = await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=6)
    result_h9 = await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=9)

    assert result_h6.wind_speed == pytest.approx(10.0)
    assert result_h9.wind_speed == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_get_forecast_cloud_base_skewt_nuageux() -> None:
    """Niveaux saturés à 925hPa → cloud_base à 800m (altitude du niveau 925hPa)."""
    # RH=92%, spread=1°C à 925hPa → saturation
    hourly = _make_hourly(
        level_925=(92.0, 800, 1.0),  # rh, geo_height, dew_point_spread
    )
    # Forcer dew_point à T - spread (T=5.0, spread=1.0 → dew_point=4.0)
    hourly["temperature_925hPa"] = [5.0] * 24
    hourly["dew_point_925hPa"] = [4.0] * 24  # spread = 5.0 - 4.0 = 1.0
    hourly["relative_humidity_925hPa"] = [92.0] * 24

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_make_mock_response(hourly))

    provider = OpenMeteoProvider(client=mock_client)
    result = await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15")

    assert result.cloud_base == 800


@pytest.mark.asyncio
async def test_get_forecast_cloud_cover_low() -> None:
    """cloud_cover_low est bien récupéré depuis les données horaires."""
    hourly = _make_hourly(cloud_cover_low=65.0)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_make_mock_response(hourly))

    provider = OpenMeteoProvider(client=mock_client)
    result = await provider.get_forecast(lat=45.83, lng=6.86, date="2026-10-15")

    assert result.cloud_cover_low == pytest.approx(65.0)
