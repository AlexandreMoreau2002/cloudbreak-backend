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
from datetime import date as date_type

import httpx

from app.services.weather_providers.base import PressureLevelData, WeatherData, WeatherProvider

logger = logging.getLogger(__name__)

# Seuils Skew-T pour la détection de la base des nuages
CLOUD_RH_THRESHOLD = 88.0  # humidité relative minimale (%)
CLOUD_DEWPOINT_SPREAD_MAX = 2.0  # T - Td maximal (°C) — air saturé

# Niveaux de pression retenus — couvrent les altitudes utiles pour la mer de nuage
# 925 hPa ≈ 800m | 850 hPa ≈ 1500m | 800 hPa ≈ 1950m | 700 hPa ≈ 3000m
PRESSURE_LEVELS = [925, 850, 800, 700]

BASE_URL = "https://api.open-meteo.com/v1/forecast"


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

    async def get_forecast(self, lat: float, lng: float, date: str, hour: int = 6) -> WeatherData:
        """
        Appelle l'API Open-Meteo et retourne un WeatherData normalisé.
        Utilise l'heure spécifiée (défaut 6h, optimal pour mer de nuage matinale).
        """
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

        hourly_vars = ",".join(
            [
                "relative_humidity_2m",
                "wind_speed_10m",
                "surface_pressure",
                "temperature_2m",
                "cloud_cover_low",
                *pressure_vars,
            ]
        )

        params: dict[str, str] = {
            "latitude": str(lat),
            "longitude": str(lng),
            "hourly": hourly_vars,
            "start_date": date,
            "end_date": date,
            "wind_speed_unit": "kmh",
            "timezone": "Europe/Paris",
        }

        logger.info(
            "open_meteo_request", extra={"lat": lat, "lng": lng, "date": date, "hour": hour}
        )

        async with self._client or httpx.AsyncClient() as client:
            response = await client.get(BASE_URL, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

        hourly = data["hourly"]
        idx = hour  # index = heure locale (0-23)

        # Construire le profil vertical par niveau de pression
        pressure_levels: list[PressureLevelData] = []
        for p in PRESSURE_LEVELS:
            temp_c = hourly.get(f"temperature_{p}hPa", [0.0] * 24)[idx]
            rh = hourly.get(f"relative_humidity_{p}hPa", [0.0] * 24)[idx]
            geo_height = hourly.get(f"geopotential_height_{p}hPa", [0.0] * 24)[idx]
            dew_point = hourly.get(f"dew_point_{p}hPa", [0.0] * 24)[idx]
            pressure_levels.append(
                PressureLevelData(
                    pressure_hpa=p,
                    altitude_m=int(geo_height),
                    temperature_c=temp_c,
                    relative_humidity=rh,
                    dew_point_spread=temp_c - dew_point,
                )
            )

        cloud_base = _estimate_cloud_base_skewt(pressure_levels)

        temp_850 = hourly.get("temperature_850hPa", [8.0] * 24)[idx]
        temp_925 = hourly.get("temperature_925hPa", [5.0] * 24)[idx]
        temp_2m = hourly.get("temperature_2m", [5.0] * 24)[idx]
        parsed_date = date_type.fromisoformat(date)

        return WeatherData(
            cloud_base=cloud_base,
            humidity=hourly.get("relative_humidity_2m", [70.0] * 24)[idx],
            wind_speed=hourly.get("wind_speed_10m", [15.0] * 24)[idx],
            temperature_2m=temp_2m,
            temperature_850hpa=temp_850,
            temperature_925hpa=temp_925,
            pressure=hourly.get("surface_pressure", [1013.0] * 24)[idx],
            cloud_cover_low=hourly.get("cloud_cover_low", [0.0] * 24)[idx],
            month=parsed_date.month,
            pressure_levels=pressure_levels,
        )
