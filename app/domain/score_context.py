"""
Logique de contexte et de présentation du score mer de nuage.

Fonctions responsables de la construction des messages contextuels,
de l'estimation des fenêtres optimales, et de la présentation complète
exposée par l'endpoint /score.
"""

from typing import TypedDict
from zoneinfo import ZoneInfo
from datetime import UTC, date as date_cls, datetime, timedelta
from math import acos, asin, atan, cos, degrees, floor, radians, sin, tan

from app.domain.weather_types import WeatherData
from app.domain.score_components import (
    ScoreConditions,
    HIGH_MIN_LOW_CLOUD_COVER,
    CLOUD_COVER_LOW_BLOCKING_THRESHOLD,
)

# ── Constantes ────────────────────────────────────────────────────────────────

PARIS_TZ = ZoneInfo("Europe/Paris")
SUNRISE_ZENITH = 90.833
SUMMER_MONTHS = {6, 7, 8}

_LABEL_CODES: dict[str, str] = {
    "high": "score.label.high",
    "medium": "score.label.medium",
    "low": "score.label.low",
    "none": "score.label.none",
}


# ── Types ─────────────────────────────────────────────────────────────────────


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


class ScoreResult(TypedDict):
    score: int
    verdict: str
    cloud_base: int
    conditions: ScoreConditions


class ScorePresentation(TypedDict):
    label_code: str
    context_code: str
    context_params: dict[str, str | int | float | bool | None]
    optimal_window_start: str | None
    optimal_window_end: str | None
    sunrise: str | None
    stability_hours: int
    cloud_layer_viz: CloudLayerViz


# ── Fonctions de présentation ─────────────────────────────────────────────────


def get_score_label_code(verdict: str) -> str:
    return _LABEL_CODES.get(verdict, "score.label.none")


def _verdict_label_code(verdict: str) -> str:
    """Code i18n stable associé au verdict."""
    return get_score_label_code(verdict)


def _context_payload(
    result: ScoreResult, weather: WeatherData, peak_altitude: int
) -> tuple[str, dict[str, str | int | float | bool | None]]:
    """Code de message contextuel cohérent avec le verdict."""
    cloud_base_gap = max(0, peak_altitude - weather.cloud_base)

    if result["verdict"] == "none":
        if weather.cloud_base >= peak_altitude:
            return ("score.context.none.cloud_base_above_summit", {})
        if weather.cloud_cover_low < CLOUD_COVER_LOW_BLOCKING_THRESHOLD:
            return ("score.context.none.low_cloud_cover", {})

    if result["verdict"] == "high":
        if weather.temperature_850hpa > weather.temperature_925hpa:
            return ("score.context.high.stable_window", {"cloud_base_gap_m": cloud_base_gap})
        return ("score.context.high.favorable_window", {})

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

    if result["verdict"] == "medium":
        if (
            weakest_condition[0] == "inversion"
            and weather.temperature_850hpa <= weather.temperature_925hpa
        ):
            return ("score.context.medium.no_inversion", {})
        if weakest_condition[0] == "cloud_base" and weather.cloud_base > peak_altitude - 150:
            return ("score.context.medium.cloud_base_close", {"cloud_base_gap_m": cloud_base_gap})
        if weakest_condition[0] == "wind" and weather.wind_speed >= 20.0:
            return ("score.context.medium.wind_fragile", {})
        return ("score.context.medium.borderline_window", {})

    if weakest_condition[0] == "wind" and weather.wind_speed >= 20.0:
        return ("score.context.low.wind_dispersion", {})
    if weakest_condition[0] == "humidity" and weather.humidity < 70.0:
        return ("score.context.low.humidity_too_low", {})
    if (
        weakest_condition[0] == "inversion"
        and weather.temperature_850hpa <= weather.temperature_925hpa
    ):
        return ("score.context.low.no_inversion", {})
    if weakest_condition[0] == "pressure" and weather.pressure < 1015.0:
        return ("score.context.low.pressure_too_low", {})
    if weakest_condition[0] == "cloud_base" and weather.cloud_base > peak_altitude - 100:
        return ("score.context.low.cloud_base_too_high", {})

    if result["score"] < 20 and weather.month in SUMMER_MONTHS:
        return ("score.context.low.sunny_clear", {"clear_sky_altitude_m": 2400})

    return ("score.context.low.conditions_too_marginal", {})


def _format_minutes(minutes: int) -> str:
    """Formate un horaire en HH:MM local."""
    normalized = minutes % (24 * 60)
    hour, minute = divmod(normalized, 60)
    return f"{hour:02d}:{minute:02d}"


def _estimate_stability_hours(result: ScoreResult, weather: WeatherData) -> int:
    """Estime une stabilité en heures à partir du score et des conditions."""
    if result["verdict"] == "none":
        return 8 if weather.cloud_cover_low >= HIGH_MIN_LOW_CLOUD_COVER else 6

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
    context_code, context_params = _context_payload(result, weather, peak_altitude)

    return ScorePresentation(
        label_code=_verdict_label_code(result["verdict"]),
        context_code=context_code,
        context_params=context_params,
        optimal_window_start=optimal_window_start,
        optimal_window_end=optimal_window_end,
        sunrise=_format_minutes(sunrise_minutes) if sunrise_minutes is not None else None,
        stability_hours=stability_hours,
        cloud_layer_viz=_cloud_layer_viz(weather, peak_altitude),
    )
