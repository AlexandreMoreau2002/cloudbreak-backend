"""
Tests du service météo avec cache Redis.

Ce service :
1. Reçoit une demande de prévision (lat, lng, date, hour)
2. Vérifie le cache Redis (clé weather:{lat}:{lng}:{date}:{hour}, TTL 10min)
3. Si cache HIT → retourne les données sans appeler l'API externe
4. Si cache MISS → appelle le WeatherProvider, stocke en cache, retourne
"""

import json
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.weather import WeatherService
from app.domain.weather_types import WeatherData


SAMPLE_WEATHER = WeatherData(
    cloud_base=1200,
    humidity=82.0,
    wind_speed=12.0,
    temperature_2m=6.0,
    temperature_850hpa=3.0,
    temperature_925hpa=5.0,
    pressure=1013.0,
    cloud_cover_low=40.0,
    month=10,
)


@pytest.fixture
def mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)  # cache MISS par défaut
    redis.setex = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.get_forecast = AsyncMock(return_value=SAMPLE_WEATHER)
    return provider


@pytest.fixture
def service(mock_redis: MagicMock, mock_provider: MagicMock) -> WeatherService:
    return WeatherService(redis=mock_redis, provider=mock_provider)


class TestCacheRedis:
    """
    Le cache Redis évite d'appeler l'API météo externe à chaque requête.
    Clé : weather:{lat}:{lng}:{date}:{hour}  — TTL : 600 secondes (10 minutes)
    """

    @pytest.mark.asyncio
    async def test_cache_miss_appelle_le_provider(
        self, service: WeatherService, mock_provider: MagicMock, mock_redis: MagicMock
    ) -> None:
        """Pas de cache → appel au provider externe."""
        mock_redis.get = AsyncMock(return_value=None)
        await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=6)
        mock_provider.get_forecast.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_stocke_en_cache(
        self, service: WeatherService, mock_redis: MagicMock
    ) -> None:
        """Après un appel provider, le résultat est mis en cache avec TTL 600s."""
        mock_redis.get = AsyncMock(return_value=None)
        await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=6)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 600

    @pytest.mark.asyncio
    async def test_cache_hit_n_appelle_pas_le_provider(
        self, service: WeatherService, mock_provider: MagicMock, mock_redis: MagicMock
    ) -> None:
        """Cache présent → provider non appelé."""
        mock_redis.get = AsyncMock(return_value=json.dumps(asdict(SAMPLE_WEATHER)).encode())
        await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=6)
        mock_provider.get_forecast.assert_not_called()

    @pytest.mark.asyncio
    async def test_cle_redis_format_correct(
        self, service: WeatherService, mock_redis: MagicMock
    ) -> None:
        """La clé Redis doit suivre le format weather:{lat}:{lng}:{date}:{hour}."""
        mock_redis.get = AsyncMock(return_value=None)
        await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=8)
        cache_key = mock_redis.get.call_args[0][0]
        assert cache_key.startswith("weather:")
        assert "45.83" in cache_key
        assert "6.86" in cache_key
        assert "2026-10-15" in cache_key
        assert "8" in cache_key

    @pytest.mark.asyncio
    async def test_cles_differentes_pour_heures_differentes(
        self, service: WeatherService, mock_redis: MagicMock
    ) -> None:
        """Deux heures différentes → deux clés cache distinctes."""
        mock_redis.get = AsyncMock(return_value=None)
        await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=6)
        key_h6 = mock_redis.get.call_args[0][0]

        mock_redis.get = AsyncMock(return_value=None)
        await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=9)
        key_h9 = mock_redis.get.call_args[0][0]

        assert key_h6 != key_h9

    @pytest.mark.asyncio
    async def test_retourne_weatherdata(self, service: WeatherService) -> None:
        """Le service retourne bien un objet WeatherData."""
        result = await service.get_forecast(lat=45.83, lng=6.86, date="2026-10-15", hour=6)
        assert isinstance(result, WeatherData)
        assert result.cloud_base == SAMPLE_WEATHER.cloud_base
