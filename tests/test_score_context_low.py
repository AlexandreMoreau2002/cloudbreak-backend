from typing import cast

from app.domain.score_context import (
    _context_payload,
    _estimate_sunrise_minutes,
    _optimal_window_from_sunrise,
    build_score_presentation,
    get_score_label_code,
)
from app.domain.score import ScoreConditions, ScoreResult
from app.domain.weather_types import PressureLevelData, WeatherData


def weather(
    *,
    cloud_base: int = 1000,
    humidity: float = 85.0,
    wind_speed: float = 10.0,
    temperature_925hpa: float = 5.0,
    temperature_850hpa: float = 8.0,
    pressure: float = 1018.0,
    cloud_cover_low: float = 70.0,
    month: int = 3,
) -> WeatherData:
    return WeatherData(
        cloud_base=cloud_base,
        humidity=humidity,
        wind_speed=wind_speed,
        temperature_2m=10.0,
        temperature_850hpa=temperature_850hpa,
        temperature_925hpa=temperature_925hpa,
        pressure=pressure,
        cloud_cover_low=cloud_cover_low,
        month=month,
    )


def result(
    *,
    score: int,
    verdict: str,
    cloud_base: int = 1000,
    cloud_base_score: float = 0.5,
    humidity_score: float = 0.5,
    wind_score: float = 0.5,
    inversion_score: float = 0.5,
    pressure_score: float = 0.5,
) -> ScoreResult:
    return cast(
        ScoreResult,
        {
            "score": score,
            "verdict": verdict,
            "cloud_base": cloud_base,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": cloud_base_score,
                    "humidity_score": humidity_score,
                    "wind_score": wind_score,
                    "inversion_score": inversion_score,
                    "pressure_score": pressure_score,
                },
            ),
        },
    )


def test_get_score_label_code_handles_known_and_unknown_verdicts() -> None:
    assert get_score_label_code("high") == "score.label.high"
    assert get_score_label_code("medium") == "score.label.medium"
    assert get_score_label_code("low") == "score.label.low"
    assert get_score_label_code("none") == "score.label.none"
    assert get_score_label_code("unexpected") == "score.label.none"


def test_context_payload_none_cloud_base_above_summit() -> None:
    assert _context_payload(
        result(score=0, verdict="none", cloud_base=1700),
        weather(cloud_base=1700, cloud_cover_low=80.0),
        peak_altitude=1500,
    ) == ("score.context.none.cloud_base_above_summit", {})


def test_context_payload_high_branches() -> None:
    stable = _context_payload(
        result(score=84, verdict="high", cloud_base=700),
        weather(cloud_base=700, temperature_925hpa=3.0, temperature_850hpa=8.0),
        peak_altitude=1500,
    )
    assert stable == ("score.context.high.stable_window", {"cloud_base_gap_m": 800})

    favorable = _context_payload(
        result(score=84, verdict="high", cloud_base=700),
        weather(cloud_base=700, temperature_925hpa=8.0, temperature_850hpa=7.0),
        peak_altitude=1500,
    )
    assert favorable == ("score.context.high.favorable_window", {})


def test_context_payload_medium_branches() -> None:
    assert _context_payload(
        result(
            score=48,
            verdict="medium",
            cloud_base=900,
            cloud_base_score=0.9,
            humidity_score=0.8,
            wind_score=0.7,
            inversion_score=0.0,
            pressure_score=0.6,
        ),
        weather(cloud_base=900, temperature_925hpa=7.0, temperature_850hpa=7.0),
        peak_altitude=1500,
    ) == ("score.context.medium.no_inversion", {})

    assert _context_payload(
        result(
            score=48,
            verdict="medium",
            cloud_base=1460,
            cloud_base_score=0.0,
            humidity_score=0.6,
            wind_score=0.7,
            inversion_score=0.8,
            pressure_score=0.9,
        ),
        weather(cloud_base=1460, cloud_cover_low=70.0),
        peak_altitude=1500,
    ) == ("score.context.medium.cloud_base_close", {"cloud_base_gap_m": 40})

    assert _context_payload(
        result(
            score=48,
            verdict="medium",
            cloud_base=900,
            cloud_base_score=0.8,
            humidity_score=0.9,
            wind_score=0.0,
            inversion_score=0.7,
            pressure_score=0.6,
        ),
        weather(cloud_base=900, wind_speed=20.0),
        peak_altitude=1500,
    ) == ("score.context.medium.wind_fragile", {})

    assert _context_payload(
        result(
            score=48,
            verdict="medium",
            cloud_base=900,
            cloud_base_score=0.8,
            humidity_score=0.0,
            wind_score=0.7,
            inversion_score=0.7,
            pressure_score=0.6,
        ),
        weather(cloud_base=900, humidity=85.0, wind_speed=10.0),
        peak_altitude=1500,
    ) == ("score.context.medium.borderline_window", {})


def test_context_payload_low_branches() -> None:
    assert _context_payload(
        result(
            score=39,
            verdict="low",
            cloud_base=1100,
            cloud_base_score=0.8,
            humidity_score=0.0,
            wind_score=0.6,
            inversion_score=0.7,
            pressure_score=0.9,
        ),
        weather(cloud_base=1100, humidity=65.0),
        peak_altitude=1500,
    ) == ("score.context.low.humidity_too_low", {})

    assert _context_payload(
        result(
            score=39,
            verdict="low",
            cloud_base=1100,
            cloud_base_score=0.8,
            humidity_score=0.6,
            wind_score=0.7,
            inversion_score=0.8,
            pressure_score=0.0,
        ),
        weather(cloud_base=1100, pressure=1010.0),
        peak_altitude=1500,
    ) == ("score.context.low.pressure_too_low", {})

    assert _context_payload(
        result(
            score=39,
            verdict="low",
            cloud_base=1460,
            cloud_base_score=0.0,
            humidity_score=0.7,
            wind_score=0.8,
            inversion_score=0.9,
            pressure_score=0.6,
        ),
        weather(cloud_base=1460),
        peak_altitude=1500,
    ) == ("score.context.low.cloud_base_too_high", {})

    assert _context_payload(
        result(
            score=19,
            verdict="low",
            cloud_base=900,
            cloud_base_score=0.9,
            humidity_score=0.8,
            wind_score=0.0,
            inversion_score=0.7,
            pressure_score=0.6,
        ),
        weather(cloud_base=900, wind_speed=10.0, month=7),
        peak_altitude=1500,
    ) == ("score.context.low.sunny_clear", {"clear_sky_altitude_m": 2400})

    assert _context_payload(
        result(
            score=20,
            verdict="low",
            cloud_base=900,
            cloud_base_score=0.9,
            humidity_score=0.8,
            wind_score=0.0,
            inversion_score=0.7,
            pressure_score=0.6,
        ),
        weather(cloud_base=900, wind_speed=10.0, month=7),
        peak_altitude=1500,
    ) == ("score.context.low.conditions_too_marginal", {})


def test_optimal_window_from_sunrise_uses_all_stability_branches() -> None:
    assert _optimal_window_from_sunrise(360, 48) == ("05:40", "07:15")
    assert _optimal_window_from_sunrise(360, 18) == ("05:45", "07:00")
    assert _optimal_window_from_sunrise(360, 8) == ("05:50", "06:45")


def test_build_score_presentation_includes_vertical_profile_and_window() -> None:
    presentation = build_score_presentation(
        result=result(
            score=48,
            verdict="medium",
            cloud_base=900,
            cloud_base_score=0.8,
            humidity_score=0.0,
            wind_score=0.7,
            inversion_score=0.7,
            pressure_score=0.6,
        ),
        weather=WeatherData(
            cloud_base=900,
            humidity=85.0,
            wind_speed=10.0,
            temperature_2m=10.0,
            temperature_850hpa=7.0,
            temperature_925hpa=6.0,
            pressure=1018.0,
            cloud_cover_low=70.0,
            month=7,
            pressure_levels=[
                PressureLevelData(
                    pressure_hpa=925,
                    altitude_m=750,
                    temperature_c=3.2,
                    relative_humidity=88.0,
                    dew_point_spread=1.5,
                ),
            ],
        ),
        date="2026-10-15",
        lat=45.83,
        lng=6.86,
        peak_altitude=1500,
    )

    assert presentation["label_code"] == "score.label.medium"
    assert presentation["context_code"] == "score.context.medium.borderline_window"
    assert presentation["stability_hours"] == 18
    assert presentation["sunrise"] is not None
    assert presentation["optimal_window_start"] is not None
    assert presentation["optimal_window_end"] is not None
    assert presentation["cloud_layer_viz"]["summit_altitude"] == 1500
    assert presentation["cloud_layer_viz"]["cloud_base"] == 900
    assert presentation["cloud_layer_viz"]["pressure_levels"][0]["pressure_hpa"] == 925


def test_estimate_sunrise_minutes_returns_none_in_polar_night() -> None:
    assert _estimate_sunrise_minutes("2026-12-21", 80.0, 0.0) is None
