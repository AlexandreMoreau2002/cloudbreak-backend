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

from datetime import UTC, date as date_cls, datetime, timedelta
from math import acos, asin, atan, cos, degrees, floor, radians, sin, tan
from typing import TypedDict
from zoneinfo import ZoneInfo

from app.domain.weather_types import WeatherData


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


class CloudLayerPoint(TypedDict):
    pressure_hpa: int
    altitude_m: int
    temperature_c: float
    relative_humidity: float
    dew_point_spread: float


class CloudLayerViz(TypedDict):
    summit_altitude: int
    cloud_base: int
    pressure_levels: list[CloudLayerPoint]


class ScorePresentation(TypedDict):
    label: str
    context_message: str
    optimal_window_start: str | None
    optimal_window_end: str | None
    sunrise: str | None
    stability_hours: int
    cloud_layer_viz: CloudLayerViz


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

PARIS_TZ = ZoneInfo("Europe/Paris")
SUNRISE_ZENITH = 90.833
SUMMER_MONTHS = {6, 7, 8}


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


def _verdict_label(verdict: str) -> str:
    """Texte humain associé au verdict du score."""
    if verdict == "high":
        return "Lève-toi tôt, ça vaut le coup"
    if verdict == "medium":
        return "Ça peut le faire"
    if verdict == "low":
        return "Pas ce coup-ci"
    return "Pas de mer de nuage"


def _context_message(result: ScoreResult, weather: WeatherData, peak_altitude: int) -> str:
    """Message contextuel déterministe lorsque le score est défavorable."""
    if result["score"] < 20 and weather.month in SUMMER_MONTHS:
        return "Pas de mer de nuage — mais ciel parfaitement dégagé au-dessus de 2400m ☀️"

    if result["verdict"] == "none":
        if weather.cloud_base >= peak_altitude:
            return "Pas de mer de nuage aujourd'hui : la base nuageuse passe au-dessus du sommet."
        if weather.cloud_cover_low < CLOUD_COVER_LOW_BLOCKING_THRESHOLD:
            return "Pas de mer de nuage aujourd'hui : la couche basse est trop faible."

    conditions = result["conditions"]
    weakest_condition = min(
        (
            ("humidity", conditions["humidity_score"]),
            ("wind", conditions["wind_score"]),
            ("inversion", conditions["inversion_score"]),
            ("pressure", conditions["pressure_score"]),
            ("cloud_base", conditions["cloud_base_score"]),
        ),
        key=lambda item: (item[1], item[0]),
    )

    if weakest_condition[0] == "wind" and weather.wind_speed >= 20.0:
        return "Pas de mer de nuage aujourd'hui : le vent disperse la couche."
    if weakest_condition[0] == "humidity" and weather.humidity < 70.0:
        return "Pas de mer de nuage aujourd'hui : l'air reste trop sec pour accrocher la couche."
    if (
        weakest_condition[0] == "inversion"
        and weather.temperature_850hpa <= weather.temperature_925hpa
    ):
        return "Pas de mer de nuage aujourd'hui : pas d'inversion thermique pour piéger les nuages."
    if weakest_condition[0] == "pressure" and weather.pressure < 1015.0:
        return "Pas de mer de nuage aujourd'hui : l'anticyclone est trop faible."
    if weakest_condition[0] == "cloud_base" and weather.cloud_base > peak_altitude - 100:
        return "Pas de mer de nuage aujourd'hui : la couche nuageuse reste trop haute."

    return "Pas de mer de nuage aujourd'hui : conditions trop limites pour une couche stable."


def _format_minutes(minutes: int) -> str:
    """Formate un horaire en HH:MM local."""
    normalized = minutes % (24 * 60)
    hour, minute = divmod(normalized, 60)
    return f"{hour:02d}:{minute:02d}"


def _estimate_stability_hours(result: ScoreResult, weather: WeatherData) -> int:
    """Estime une stabilité en heures à partir du score et des conditions."""
    if result["verdict"] == "none":
        return 8 if weather.cloud_cover_low >= CLOUD_COVER_LOW_BLOCKING_THRESHOLD else 6

    cond = result["conditions"]
    stability_index = (
        0.35 * cond["pressure_score"]
        + 0.30 * cond["wind_score"]
        + 0.20 * cond["cloud_base_score"]
        + 0.15 * cond["inversion_score"]
    )

    if result["score"] >= 80 and stability_index >= 0.75:
        return 48
    if result["score"] >= 70 and stability_index >= 0.60:
        return 36
    if result["score"] >= 40:
        return 18
    return 8


def _estimate_sunrise_minutes(date: str, lat: float, lng: float) -> int | None:
    """
    Estime le lever du soleil via une approximation NOAA simple.

    Retourne l'heure locale Europe/Paris en minutes depuis minuit.
    """
    current_date = date_cls.fromisoformat(date)
    day_of_year = current_date.timetuple().tm_yday
    lng_hour = lng / 15.0
    approximate_time = day_of_year + ((6.0 - lng_hour) / 24.0)
    mean_anomaly = 0.9856 * approximate_time - 3.289

    true_longitude = mean_anomaly + 1.916 * sin(radians(mean_anomaly))
    true_longitude += 0.020 * sin(radians(2.0 * mean_anomaly)) + 282.634
    true_longitude %= 360.0

    right_ascension = degrees(atan(0.91764 * tan(radians(true_longitude))))
    right_ascension %= 360.0
    l_quadrant = floor(true_longitude / 90.0) * 90.0
    ra_quadrant = floor(right_ascension / 90.0) * 90.0
    right_ascension += l_quadrant - ra_quadrant
    right_ascension_hours = right_ascension / 15.0

    sin_dec = 0.39782 * sin(radians(true_longitude))
    cos_dec = cos(asin(sin_dec))
    cos_h = (cos(radians(SUNRISE_ZENITH)) - (sin_dec * sin(radians(lat)))) / (
        cos_dec * cos(radians(lat))
    )

    if cos_h > 1.0 or cos_h < -1.0:
        return None

    hour_angle = 360.0 - degrees(acos(cos_h))
    hour_angle_hours = hour_angle / 15.0
    local_mean_time = (
        hour_angle_hours + right_ascension_hours - (0.06571 * approximate_time) - 6.622
    )
    utc_hours = (local_mean_time - lng_hour) % 24.0
    utc_dt = datetime.combine(current_date, datetime.min.time(), tzinfo=UTC) + timedelta(
        hours=utc_hours
    )
    local_dt = utc_dt.astimezone(PARIS_TZ)
    return local_dt.hour * 60 + local_dt.minute


def _optimal_window_from_sunrise(
    sunrise_minutes: int | None,
    stability_hours: int,
) -> tuple[str | None, str | None]:
    """Construit une fenêtre optimale autour du lever du soleil."""
    if sunrise_minutes is None:
        return None, None

    if stability_hours >= 36:
        start_offset = -20
        end_offset = 75
    elif stability_hours >= 18:
        start_offset = -15
        end_offset = 60
    else:
        start_offset = -10
        end_offset = 45

    return (
        _format_minutes(sunrise_minutes + start_offset),
        _format_minutes(sunrise_minutes + end_offset),
    )


def _cloud_layer_viz(weather: WeatherData, peak_altitude: int) -> CloudLayerViz:
    """Transforme le profil vertical météo en payload de visualisation."""
    return CloudLayerViz(
        summit_altitude=peak_altitude,
        cloud_base=weather.cloud_base,
        pressure_levels=[
            CloudLayerPoint(
                pressure_hpa=level.pressure_hpa,
                altitude_m=level.altitude_m,
                temperature_c=level.temperature_c,
                relative_humidity=level.relative_humidity,
                dew_point_spread=level.dew_point_spread,
            )
            for level in weather.pressure_levels
        ],
    )


def build_score_presentation(
    result: ScoreResult,
    weather: WeatherData,
    date: str,
    lat: float,
    lng: float,
    peak_altitude: int,
) -> ScorePresentation:
    """Construit les champs de présentation exposés par le endpoint score."""
    stability_hours = _estimate_stability_hours(result, weather)
    sunrise_minutes = _estimate_sunrise_minutes(date, lat, lng)
    optimal_window_start, optimal_window_end = _optimal_window_from_sunrise(
        sunrise_minutes, stability_hours
    )

    return ScorePresentation(
        label=_verdict_label(result["verdict"]),
        context_message=_context_message(result, weather, peak_altitude),
        optimal_window_start=optimal_window_start,
        optimal_window_end=optimal_window_end,
        sunrise=_format_minutes(sunrise_minutes) if sunrise_minutes is not None else None,
        stability_hours=stability_hours,
        cloud_layer_viz=_cloud_layer_viz(weather, peak_altitude),
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
