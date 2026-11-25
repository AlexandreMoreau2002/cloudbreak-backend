"""
Composantes individuelles du score mer de nuage.

Chaque fonction calcule un sous-score normalisé entre 0.0 et 1.0.
Ces composantes sont combinées par calculate_score() dans score.py.
"""

from typing import TypedDict

from app.domain.weather_types import WeatherData

# ── Paramètres de l'algorithme ────────────────────────────────────────────────

# Conditions bloquantes
CLOUD_COVER_LOW_BLOCKING_THRESHOLD = 45.0  # % — sous ce seuil, couche trop fragmentée pour scorer

# cloud_base_condition :
#   score maximum si cloud_base ≤ CLOUD_BASE_OPTIMAL (bien sous le sommet)
#   score nul si cloud_base ≥ CLOUD_BASE_MAX (au-dessus du sommet + marge)
CLOUD_BASE_OPTIMAL_MARGIN = 200  # mètres sous le sommet → score max
CLOUD_BASE_MAX_MARGIN = 500  # mètres au-dessus du sommet → score nul

# humidity_score :
#   score max à HUMIDITY_MAX, score nul à HUMIDITY_MIN
HUMIDITY_MAX = 95.0  # %
HUMIDITY_MIN = 60.0  # % — sous 60% quasi impossible de former une mer de nuage

# wind_score :
#   score max à WIND_MIN km/h, score nul à WIND_MAX km/h
WIND_MIN = 5.0  # km/h — calme parfait
WIND_MAX = 30.0  # km/h — au-delà le vent disperse les nuages

# inversion_score — comparaison T850hPa vs T925hPa :
#   delta = T(850hPa) - T(925hPa)
#   Si positif → inversion (air plus chaud en altitude) → favorable
INVERSION_STRONG = 5.0  # °C de delta → inversion marquée → score max
INVERSION_ABSENT = -3.0  # °C de delta → gradient normal → score nul

# pressure_score :
#   Pression élevée = anticyclone = favorable
PRESSURE_HIGH = 1025.0  # hPa → score 1.0
PRESSURE_LOW = 1010.0  # hPa → score 0.0

# Poids des composantes (somme = 1.0)
WEIGHT_CLOUD_BASE = 0.35
WEIGHT_HUMIDITY = 0.20
WEIGHT_WIND = 0.15
WEIGHT_INVERSION = 0.20
WEIGHT_PRESSURE = 0.10

HIGH_MIN_LOW_CLOUD_COVER = 55.0
HIGH_MIN_MARGIN_BELOW_SUMMIT = 150
NO_INVERSION_SCORE_FACTOR = 0.55
HIGH_CLOUD_BASE_SCORE_FACTOR = 0.78
LOW_CLOUD_COVER_SCORE_FACTOR = 0.82
STRONG_WIND_SCORE_FACTOR = 0.6
NO_INVERSION_SCORE_CAP = 39
HIGH_CLOUD_BASE_SCORE_CAP = 55
LOW_CLOUD_COVER_SCORE_CAP = 55
STRONG_WIND_SCORE_CAP = 39


# ── Types ─────────────────────────────────────────────────────────────────────


class ScoreConditions(TypedDict):
    cloud_base_score: float
    humidity_score: float
    wind_score: float
    inversion_score: float
    pressure_score: float


# ── Fonctions de composantes ──────────────────────────────────────────────────


def _cloud_base_component(cloud_base: int, peak_altitude: int) -> float:
    """
    Composante cloud_base (poids 0.35) — la plus importante.

    Logique :
    - Si cloud_base ≤ (peak_altitude - CLOUD_BASE_OPTIMAL_MARGIN) → score 1.0
      Les nuages sont bien sous le sommet, mer de nuage très probable.
    - Si cloud_base ≥ (peak_altitude + CLOUD_BASE_MAX_MARGIN) → score 0.0
      Les nuages sont au-dessus du sommet, pas de mer de nuage.
    - Entre les deux → interpolation linéaire.
    """
    optimal_threshold = peak_altitude - CLOUD_BASE_OPTIMAL_MARGIN
    max_threshold = peak_altitude + CLOUD_BASE_MAX_MARGIN

    if cloud_base <= optimal_threshold:
        return 1.0
    if cloud_base >= max_threshold:
        return 0.0

    range_size = max_threshold - optimal_threshold
    return 1.0 - (cloud_base - optimal_threshold) / range_size


def _humidity_component(humidity: float) -> float:
    """
    Composante humidité (poids 0.20).
    Humidité élevée → nuages plus faciles à former → favorable.
    Interpolation linéaire entre HUMIDITY_MIN et HUMIDITY_MAX.
    """
    return max(0.0, min(1.0, (humidity - HUMIDITY_MIN) / (HUMIDITY_MAX - HUMIDITY_MIN)))


def _wind_component(wind_speed: float) -> float:
    """
    Composante vent (poids 0.15).
    Vent faible → nuages stables → favorable.
    Vent fort (> 30 km/h) → dispersion → défavorable.
    """
    if wind_speed <= WIND_MIN:
        return 1.0
    if wind_speed >= WIND_MAX:
        return 0.0
    return 1.0 - (wind_speed - WIND_MIN) / (WIND_MAX - WIND_MIN)


def _inversion_component(temp_925: float, temp_850: float) -> float:
    """
    Composante inversion thermique (poids 0.20).

    Comparaison T(850hPa) vs T(925hPa) — niveaux de pression standard.
    delta = T(850hPa) - T(925hPa)
    - delta positif fort (INVERSION_STRONG) → inversion marquée → score 1.0
    - delta négatif (INVERSION_ABSENT) → gradient normal → score 0.0
    """
    delta = temp_850 - temp_925
    return max(0.0, min(1.0, (delta - INVERSION_ABSENT) / (INVERSION_STRONG - INVERSION_ABSENT)))


def _pressure_component(pressure: float) -> float:
    """
    Composante pression (poids 0.10).
    Pression élevée (anticyclone) → conditions stables → favorable.
    Interpolation linéaire entre PRESSURE_LOW et PRESSURE_HIGH.
    """
    return max(0.0, min(1.0, (pressure - PRESSURE_LOW) / (PRESSURE_HIGH - PRESSURE_LOW)))


def _zero_conditions() -> ScoreConditions:
    """Retourne des conditions toutes à zéro (cas bloquants)."""
    return ScoreConditions(
        cloud_base_score=0.0,
        humidity_score=0.0,
        wind_score=0.0,
        inversion_score=0.0,
        pressure_score=0.0,
    )


def _apply_score_caps(raw_score: int, weather: WeatherData, peak_altitude: int) -> int:
    """Plafonne les faux positifs évidents avant de dériver le verdict."""
    capped_score = raw_score

    if weather.temperature_850hpa <= weather.temperature_925hpa:
        capped_score = min(
            capped_score,
            min(NO_INVERSION_SCORE_CAP, int(round(raw_score * NO_INVERSION_SCORE_FACTOR))),
        )
    if weather.cloud_base > peak_altitude - HIGH_MIN_MARGIN_BELOW_SUMMIT:
        capped_score = min(
            capped_score,
            min(HIGH_CLOUD_BASE_SCORE_CAP, int(round(raw_score * HIGH_CLOUD_BASE_SCORE_FACTOR))),
        )
    if weather.cloud_cover_low < HIGH_MIN_LOW_CLOUD_COVER:
        capped_score = min(
            capped_score,
            min(LOW_CLOUD_COVER_SCORE_CAP, int(round(raw_score * LOW_CLOUD_COVER_SCORE_FACTOR))),
        )
    if weather.wind_speed >= 20.0:
        capped_score = min(
            capped_score,
            min(STRONG_WIND_SCORE_CAP, int(round(raw_score * STRONG_WIND_SCORE_FACTOR))),
        )

    return max(0, capped_score)
