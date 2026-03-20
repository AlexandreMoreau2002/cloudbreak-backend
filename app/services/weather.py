"""
Service météo avec cache Redis.

Rôle : intercepter les appels provider avec un cache Redis TTL 10min.
Chaque requête unique (lat, lng, date, hour) est mise en cache après le premier appel.
Les requêtes suivantes pour le même sommet/date/heure retournent le cache sans appel API.

Clé Redis : weather:{lat}:{lng}:{date}:{hour}
TTL       : 600 secondes (10 minutes)
"""

import json
import logging
from typing import Any
from dataclasses import asdict
from redis.asyncio import Redis
from app.domain.weather_types import PressureLevelData, WeatherData, WeatherProvider

logger = logging.getLogger(__name__)

CACHE_TTL = 600  # 10 minutes en secondes


def _weather_data_from_dict(data: dict[str, Any]) -> WeatherData:
    """Désérialise un WeatherData depuis un dict JSON (reconstruit les PressureLevelData)."""
    pressure_levels = [PressureLevelData(**pl) for pl in data.get("pressure_levels", [])]
    return WeatherData(
        cloud_base=data["cloud_base"],
        humidity=data["humidity"],
        wind_speed=data["wind_speed"],
        temperature_2m=data["temperature_2m"],
        temperature_850hpa=data["temperature_850hpa"],
        temperature_925hpa=data["temperature_925hpa"],
        pressure=data["pressure"],
        cloud_cover_low=data["cloud_cover_low"],
        month=data["month"],
        pressure_levels=pressure_levels,
    )


class WeatherService:
    def __init__(self, redis: Redis, provider: WeatherProvider) -> None:
        self._redis = redis
        self._provider = provider

    async def get_forecast(self, lat: float, lng: float, date: str, hour: int = 6) -> WeatherData:
        """
        Retourne les données météo pour une coordonnée, une date et une heure.
        1. Vérifie le cache Redis
        2. Si HIT → désérialise et retourne
        3. Si MISS → appelle le provider, sérialise, stocke en cache, retourne
        """
        cache_key = f"weather:{lat}:{lng}:{date}:{hour}"

        cached = await self._redis.get(cache_key)
        if cached:
            logger.info("weather_cache_hit", extra={"key": cache_key})
            return _weather_data_from_dict(json.loads(cached))

        logger.info("weather_cache_miss", extra={"key": cache_key})
        weather = await self._provider.get_forecast(lat=lat, lng=lng, date=date, hour=hour)

        await self._redis.setex(cache_key, CACHE_TTL, json.dumps(asdict(weather)))
        return weather
