"""
Provider Open-Meteo — gratuit, sans clé API, données altimétriques.

API utilisée : https://api.open-meteo.com/v1/forecast
Documentation : https://open-meteo.com/en/docs

Comment on calcule cloud_base — méthode Skew-T :
  On scanne les niveaux de pression de bas en haut (du sol vers le sommet).
  Le premier niveau où RH >= 88% ET T-Td < 2°C définit la base des nuages.
  L'altitude est fournie directement par Open-Meteo via geopotential_height (MSL).
  Si aucun niveau ne satisfait ces critères → ciel clair → cloud_base = 5000m.

Pourquoi Skew-T et non cloud_cover :
  cloud_cover par niveau de pression est non fiable (GitHub Open-Meteo #416).
  La méthode RH + dew point spread est validée météorologiquement.

Comment on calcule l'inversion thermique :
  On compare T(850hPa) avec T(925hPa).
  Si T(850hPa) > T(925hPa) → inversion présente → favorable pour mer de nuage.
"""

import logging
from typing import cast
from datetime import date as date_type
from datetime import datetime, timedelta

import httpx

from app.domain.weather_types import PressureLevelData, WeatherData, WeatherProvider

logger = logging.getLogger(__name__)

# Seuils Skew-T pour la détection de la base des nuages
CLOUD_RH_THRESHOLD = 88.0  # humidité relative minimale (%)
CLOUD_DEWPOINT_SPREAD_MAX = 2.0  # T - Td maximal (°C) — air saturé

# Niveaux de pression retenus — couvrent les altitudes utiles pour la mer de nuage
# 925 hPa ≈ 800m | 850 hPa ≈ 1500m | 800 hPa ≈ 1950m | 700 hPa ≈ 3000m
PRESSURE_LEVELS = [925, 850, 800, 700]

BASE_URL = "https://api.open-meteo.com/v1/forecast"
HourlyPayload = dict[str, list[object]]


def _estimate_cloud_base_skewt(levels: list[PressureLevelData]) -> int:
    """
    Estime la base des nuages via méthode Skew-T.
    Scan bottom-up : premier niveau où RH >= 88% ET T-Td < 2°C.
    Retourne l'altitude MSL du niveau en mètres, ou 5000 si ciel clair.
    """
    for level in sorted(levels, key=lambda lv: lv.altitude_m):
        rh_ok = level.relative_humidity >= CLOUD_RH_THRESHOLD
        spread_ok = level.dew_point_spread < CLOUD_DEWPOINT_SPREAD_MAX
        if rh_ok and spread_ok:
            return level.altitude_m
    return 5000


class OpenMeteoProvider(WeatherProvider):
    """Provider principal — Open-Meteo (gratuit, sans clé)."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @staticmethod
    def _hourly_variables() -> str:
        pressure_vars: list[str] = []
        for p in PRESSURE_LEVELS:
            pressure_vars.extend(
                [
                    f"temperature_{p}hPa",
                    f"relative_humidity_{p}hPa",
                    f"geopotential_height_{p}hPa",
                    f"dew_point_{p}hPa",
                ]
            )

        return ",".join(
            [
                "relative_humidity_2m",
                "wind_speed_10m",
                "surface_pressure",
                "temperature_2m",
                "cloud_cover_low",
                *pressure_vars,
            ]
        )

    async def _get_hourly_payload(
        self,
        lat: float,
        lng: float,
        start_date: str,
        end_date: str,
    ) -> HourlyPayload:
        """Récupère une plage Open-Meteo, commune aux lectures simple et hebdomadaire."""
        params: dict[str, str] = {
            "latitude": str(lat),
            "longitude": str(lng),
            "hourly": self._hourly_variables(),
            "start_date": start_date,
            "end_date": end_date,
            "wind_speed_unit": "kmh",
            "timezone": "Europe/Paris",
        }

        logger.info(
            "open_meteo_request",
            extra={"lat": lat, "lng": lng, "start_date": start_date, "end_date": end_date},
        )

        async with self._client or httpx.AsyncClient() as client:
            response = await client.get(BASE_URL, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

        return cast(HourlyPayload, data["hourly"])

    @staticmethod
    def _weather_from_hourly(hourly: HourlyPayload, date: str, index: int) -> WeatherData:
        """Normalise les vecteurs horaires Open-Meteo pour une cellule donnée."""

        def value(name: str, fallback: float) -> float:
            values = hourly.get(name)
            if values is None or index >= len(values):
                return fallback
            raw_value = values[index]
            if not isinstance(raw_value, int | float):
                raise ValueError(f"Valeur météo invalide pour {name}")
            return float(raw_value)

        pressure_levels: list[PressureLevelData] = []
        for p in PRESSURE_LEVELS:
            temp_c = value(f"temperature_{p}hPa", 0.0)
            rh = value(f"relative_humidity_{p}hPa", 0.0)
            geo_height = value(f"geopotential_height_{p}hPa", 0.0)
            dew_point = value(f"dew_point_{p}hPa", 0.0)
            pressure_levels.append(
                PressureLevelData(
                    pressure_hpa=p,
                    altitude_m=int(geo_height),
                    temperature_c=temp_c,
                    relative_humidity=rh,
                    dew_point_spread=temp_c - dew_point,
                )
            )

        return WeatherData(
            cloud_base=_estimate_cloud_base_skewt(pressure_levels),
            humidity=value("relative_humidity_2m", 70.0),
            wind_speed=value("wind_speed_10m", 15.0),
            temperature_2m=value("temperature_2m", 5.0),
            temperature_850hpa=value("temperature_850hPa", 8.0),
            temperature_925hpa=value("temperature_925hPa", 5.0),
            pressure=value("surface_pressure", 1013.0),
            cloud_cover_low=value("cloud_cover_low", 0.0),
            month=date_type.fromisoformat(date).month,
            pressure_levels=pressure_levels,
        )

    @staticmethod
    def _hourly_indexes(hourly: HourlyPayload) -> dict[tuple[str, int], int]:
        """Indexe les valeurs par date et heure locales retournées par Open-Meteo."""
        timestamps = hourly.get("time")
        if timestamps is None:
            raise ValueError("Horodatages Open-Meteo absents")

        indexes: dict[tuple[str, int], int] = {}
        for index, timestamp in enumerate(timestamps):
            if not isinstance(timestamp, str):
                raise ValueError("Horodatage Open-Meteo invalide")
            local_datetime = datetime.fromisoformat(timestamp)
            indexes.setdefault((local_datetime.date().isoformat(), local_datetime.hour), index)
        return indexes

    async def get_forecast(self, lat: float, lng: float, date: str, hour: int = 6) -> WeatherData:
        """Retourne la prévision normalisée d'une heure sans changer le contrat existant."""
        hourly = await self._get_hourly_payload(lat, lng, date, date)
        return self._weather_from_hourly(hourly, date, hour)

    async def get_week_forecast(
        self,
        lat: float,
        lng: float,
        start_date: str,
        hours: tuple[int, ...],
    ) -> dict[str, dict[int, WeatherData]]:
        """Retourne les heures utiles de sept jours depuis une seule réponse Open-Meteo."""
        first_day = date_type.fromisoformat(start_date)
        days = [first_day + timedelta(days=offset) for offset in range(7)]
        hourly = await self._get_hourly_payload(lat, lng, start_date, days[-1].isoformat())
        indexes = self._hourly_indexes(hourly)
        return {
            day.isoformat(): {
                hour: self._weather_from_hourly(
                    hourly,
                    day.isoformat(),
                    indexes[(day.isoformat(), hour)],
                )
                for hour in hours
            }
            for day in days
        }
