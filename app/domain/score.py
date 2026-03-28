"""
Algorithme de score mer de nuage.

Conditions bloquantes (éliminatoires — retournent verdict "none") :
  1. cloud_base >= peak_altitude → les nuages sont au-dessus ou au niveau du sommet
     → pas de mer de nuage physiquement possible
  2. cloud_cover_low < 45.0% → couche basse trop fragmentée
     → pas assez de nuages bas pour mériter un score

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

from app.domain.weather_types import WeatherData
from app.domain.score_components import (
    ScoreConditions,
    WEIGHT_WIND,
    WEIGHT_HUMIDITY,
    WEIGHT_PRESSURE,
    WEIGHT_INVERSION,
    WEIGHT_CLOUD_BASE,
    HIGH_MIN_LOW_CLOUD_COVER,
    HIGH_MIN_MARGIN_BELOW_SUMMIT,
    CLOUD_COVER_LOW_BLOCKING_THRESHOLD,
    _wind_component,
    _zero_conditions,
    _apply_score_caps,
    _pressure_component,
    _humidity_component,
    _inversion_component,
    _cloud_base_component,
)
from app.domain.score_context import (
    CloudLayerPoint,
    CloudLayerViz,
    ScorePresentation,
    ScoreResult,
    _context_payload,
    _estimate_stability_hours,
    _estimate_sunrise_minutes,
    _format_minutes,
    _optimal_window_from_sunrise,
    _verdict_label_code,
    build_score_presentation,
    get_score_label_code,
)

# Re-export all public names so existing imports stay valid
__all__ = [
    "ScoreConditions",
    "ScoreResult",
    "CloudLayerPoint",
    "CloudLayerViz",
    "ScorePresentation",
    "get_score_label_code",
    "_verdict_label_code",
    "_context_payload",
    "_apply_score_caps",
    "_cloud_base_component",
    "_humidity_component",
    "_wind_component",
    "_inversion_component",
    "_pressure_component",
    "_zero_conditions",
    "_estimate_stability_hours",
    "_estimate_sunrise_minutes",
    "_optimal_window_from_sunrise",
    "_format_minutes",
    "build_score_presentation",
    "calculate_score",
]


# ── Fonction principale ───────────────────────────────────────────────────────


def calculate_score(weather: WeatherData, peak_altitude: int) -> ScoreResult:
    """
    Calcule le score de probabilité de mer de nuage.

    Conditions bloquantes (éliminatoires) vérifiées en premier :
    1. cloud_base >= peak_altitude → nuages au-dessus du sommet → "none"
    2. cloud_cover_low < 45% → couche trop fragmentée → "none"

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

    # Condition bloquante 2 : couverture nuageuse basse insuffisante → pas de couche crédible
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
    final_score = _apply_score_caps(final_score, weather, peak_altitude)

    if (
        final_score >= 70
        and weather.temperature_850hpa > weather.temperature_925hpa
        and weather.cloud_base <= peak_altitude - HIGH_MIN_MARGIN_BELOW_SUMMIT
        and weather.cloud_cover_low >= HIGH_MIN_LOW_CLOUD_COVER
    ):
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
