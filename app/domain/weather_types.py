"""
Interface abstraite WeatherProvider.

Tout provider météo doit implémenter cette interface.
L'algo de score ne connaît que WeatherData — jamais le provider concret.

WeatherData — champs normalisés :
  cloud_base          : int    altitude de la base des nuages MSL (mètres), déduite par Skew-T
  humidity            : float  humidité relative 2m en % (0-100)
  wind_speed          : float  vitesse du vent 10m en km/h
  temperature_2m      : float  température surface 2m (°C)
  temperature_850hpa  : float  température à ~1500m / 850 hPa (°C)
  temperature_925hpa  : float  température à ~800m / 925 hPa (°C) — pour inversion
  pressure            : float  pression de surface en hPa
  cloud_cover_low     : float  couverture nuageuse basse en % (0-100)
  month               : int    mois de la prévision (1-12) — pour la saisonnalité
  pressure_levels     : list   profil vertical complet (PressureLevelData)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PressureLevelData:
    pressure_hpa: int
    altitude_m: int  # géopotentiel MSL
    temperature_c: float
    relative_humidity: float
    dew_point_spread: float  # T - Td


@dataclass
class WeatherData:
    cloud_base: int
    humidity: float
    wind_speed: float
    temperature_2m: float
    temperature_850hpa: float
    temperature_925hpa: float
    pressure: float
    cloud_cover_low: float
    month: int
    pressure_levels: list[PressureLevelData] = field(default_factory=list)


class WeatherProvider(ABC):
    @abstractmethod
    async def get_forecast(self, lat: float, lng: float, date: str, hour: int = 6) -> WeatherData:
        """
        Retourne les données météo normalisées pour une coordonnée et une date.

        Args:
            lat  : latitude (ex: 45.8326)
            lng  : longitude (ex: 6.8652)
            date : date ISO 8601 (ex: "2026-10-15")
            hour : heure locale (0-23), défaut 6h (optimal pour mer de nuage)

        Returns:
            WeatherData normalisé — même structure quel que soit le provider
        """
