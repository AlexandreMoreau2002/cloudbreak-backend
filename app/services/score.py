"""
Algorithme de score mer de nuage.

Conditions bloquantes (éliminatoires — retournent verdict "none") :
  1. cloud_base >= peak_altitude → les nuages sont au-dessus ou au niveau du sommet
     → pas de mer de nuage physiquement possible
  2. cloud_cover_low < 20.0% → ciel trop dégagé, pas assez de nuages bas
     → pas de mer de nuage

Score conditionnel (seulement si conditions non bloquantes) :
  Les 4 composantes sont des indicateurs de qualité de la mer de nuage,
  présentés honnêtement — pas un score de précision calibré.

  cloud_base_score  : nuages bien sous le sommet → score 1.0
  humidity_score    : humidité élevée → formation des nuages favorisée
  wind_score        : vent faible → nuages stables
  inversion_score   : T(850hPa) > T(925hPa) → inversion thermique → piège les nuages
  pressure_score    : haute pression → conditions stables

Verdicts :
  none   : conditions bloquantes (pas de mer de nuage possible)
  high   : score ≥ 70
  medium : 40 ≤ score < 70
  low    : score < 40
"""

from typing import TypedDict

from app.services.weather_providers.base import WeatherData


# ── Types ─────────────────────────────────────────────────────────────────────


class ScoreConditions(TypedDict):
    cloud_base_score: float
    humidity_score: float
    wind_score: float
    inversion_score: float
    pressure_score: float


class ScoreResult(TypedDict):
    score: int
    verdict: str
    cloud_base: int
    conditions: ScoreConditions


# ── Paramètres de l'algorithme ────────────────────────────────────────────────

# Conditions bloquantes
CLOUD_COVER_LOW_BLOCKING_THRESHOLD = 20.0  # % — sous ce seuil, ciel trop dégagé

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


# ── Fonction principale ───────────────────────────────────────────────────────


def calculate_score(weather: WeatherData, peak_altitude: int) -> ScoreResult:
    """
    Calcule le score de probabilité de mer de nuage.

    Conditions bloquantes (éliminatoires) vérifiées en premier :
    1. cloud_base >= peak_altitude → nuages au-dessus du sommet → "none"
    2. cloud_cover_low < 20% → ciel trop dégagé → "none"

    Si aucune condition bloquante : calcul du score sur 4 composantes pondérées.

    Args:
        weather       : données météo normalisées
        peak_altitude : altitude du sommet en mètres

    Returns:
        ScoreResult avec score (0-100), verdict, cloud_base, et détail des composantes
    """
    # Condition bloquante 1 : nuages au-dessus du sommet → mer de nuage physiquement impossible
    if weather.cloud_base >= peak_altitude:
        return ScoreResult(
            score=0,
            verdict="none",
            cloud_base=weather.cloud_base,
            conditions=_zero_conditions(),
        )

    # Condition bloquante 2 : couverture nuageuse basse insuffisante → ciel trop dégagé
    if weather.cloud_cover_low < CLOUD_COVER_LOW_BLOCKING_THRESHOLD:
        return ScoreResult(
            score=0,
            verdict="none",
            cloud_base=weather.cloud_base,
            conditions=_zero_conditions(),
        )

    cb = _cloud_base_component(weather.cloud_base, peak_altitude)
    hum = _humidity_component(weather.humidity)
    wind = _wind_component(weather.wind_speed)
    inv = _inversion_component(weather.temperature_925hpa, weather.temperature_850hpa)
    pres = _pressure_component(weather.pressure)

    raw_score = (
        WEIGHT_CLOUD_BASE * cb
        + WEIGHT_HUMIDITY * hum
        + WEIGHT_WIND * wind
        + WEIGHT_INVERSION * inv
        + WEIGHT_PRESSURE * pres
    )

    final_score = int(round(min(1.0, raw_score) * 100))
    final_score = max(0, final_score)

    if final_score >= 70:
        verdict = "high"
    elif final_score >= 40:
        verdict = "medium"
    else:
        verdict = "low"

    return ScoreResult(
        score=final_score,
        verdict=verdict,
        cloud_base=weather.cloud_base,
        conditions=ScoreConditions(
            cloud_base_score=round(cb, 3),
            humidity_score=round(hum, 3),
            wind_score=round(wind, 3),
            inversion_score=round(inv, 3),
            pressure_score=round(pres, 3),
        ),
    )
