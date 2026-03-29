from typing import cast

from app.domain.score_context import (
    _context_payload,
    _optimal_window_from_sunrise,
    ScoreConditions,
    ScoreResult,
)
from app.domain.weather_types import WeatherData


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


def medium_result(conditions: ScoreConditions, score: int = 55) -> ScoreResult:
    return cast(
        ScoreResult,
        {
            "score": score,
            "verdict": "medium",
            "cloud_base": 1000,
            "conditions": conditions,
        },
    )


def test_medium_context_no_inversion() -> None:
    result = medium_result(
        cast(
            ScoreConditions,
            {
                "cloud_base_score": 0.8,
                "humidity_score": 0.7,
                "wind_score": 0.6,
                "inversion_score": 0.1,
                "pressure_score": 0.5,
            },
        )
    )

    assert _context_payload(
        result,
        weather(temperature_925hpa=8.0, temperature_850hpa=7.0),
        peak_altitude=1500,
    ) == ("score.context.medium.no_inversion", {})


def test_medium_context_cloud_base_close() -> None:
    result = medium_result(
        cast(
            ScoreConditions,
            {
                "cloud_base_score": 0.1,
                "humidity_score": 0.7,
                "wind_score": 0.6,
                "inversion_score": 0.8,
                "pressure_score": 0.5,
            },
        )
    )

    assert _context_payload(
        result,
        weather(cloud_base=1400),
        peak_altitude=1500,
    ) == ("score.context.medium.cloud_base_close", {"cloud_base_gap_m": 100})


def test_medium_context_wind_fragile() -> None:
    result = medium_result(
        cast(
            ScoreConditions,
            {
                "cloud_base_score": 0.8,
                "humidity_score": 0.7,
                "wind_score": 0.1,
                "inversion_score": 0.8,
                "pressure_score": 0.5,
            },
        )
    )

    assert _context_payload(
        result,
        weather(wind_speed=20.0),
        peak_altitude=1500,
    ) == ("score.context.medium.wind_fragile", {})


def test_medium_context_borderline_window_fallback() -> None:
    result = medium_result(
        cast(
            ScoreConditions,
            {
                "cloud_base_score": 0.6,
                "humidity_score": 0.1,
                "wind_score": 0.7,
                "inversion_score": 0.8,
                "pressure_score": 0.5,
            },
        )
    )

    assert _context_payload(
        result,
        weather(humidity=62.0),
        peak_altitude=1500,
    ) == ("score.context.medium.borderline_window", {})


def test_none_context_cloud_base_above_summit() -> None:
    result = cast(
        ScoreResult,
        {
            "score": 0,
            "verdict": "none",
            "cloud_base": 0,
            "conditions": cast(ScoreConditions, {}),
        },
    )

    assert _context_payload(
        result,
        weather(cloud_base=1600, cloud_cover_low=80.0),
        peak_altitude=1500,
    ) == ("score.context.none.cloud_base_above_summit", {})


def test_high_context_favorable_window() -> None:
    result = cast(
        ScoreResult,
        {
            "score": 82,
            "verdict": "high",
            "cloud_base": 700,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": 1.0,
                    "humidity_score": 1.0,
                    "wind_score": 1.0,
                    "inversion_score": 1.0,
                    "pressure_score": 1.0,
                },
            ),
        },
    )

    assert _context_payload(
        result,
        weather(temperature_925hpa=9.0, temperature_850hpa=8.0),
        peak_altitude=1500,
    ) == ("score.context.high.favorable_window", {})


def test_low_context_humidity_pressure_cloud_base_and_fallback() -> None:
    humidity_result = cast(
        ScoreResult,
        {
            "score": 30,
            "verdict": "low",
            "cloud_base": 900,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": 0.6,
                    "humidity_score": 0.1,
                    "wind_score": 0.7,
                    "inversion_score": 0.8,
                    "pressure_score": 0.5,
                },
            ),
        },
    )
    pressure_result = cast(
        ScoreResult,
        {
            "score": 30,
            "verdict": "low",
            "cloud_base": 900,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": 0.7,
                    "humidity_score": 0.8,
                    "wind_score": 0.6,
                    "inversion_score": 0.9,
                    "pressure_score": 0.1,
                },
            ),
        },
    )
    cloud_base_result = cast(
        ScoreResult,
        {
            "score": 30,
            "verdict": "low",
            "cloud_base": 900,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": 0.1,
                    "humidity_score": 0.8,
                    "wind_score": 0.7,
                    "inversion_score": 0.9,
                    "pressure_score": 0.5,
                },
            ),
        },
    )
    fallback_result = cast(
        ScoreResult,
        {
            "score": 25,
            "verdict": "low",
            "cloud_base": 900,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": 0.7,
                    "humidity_score": 0.1,
                    "wind_score": 0.8,
                    "inversion_score": 0.9,
                    "pressure_score": 0.6,
                },
            ),
        },
    )

    assert _context_payload(
        humidity_result,
        weather(humidity=65.0),
        peak_altitude=1500,
    ) == ("score.context.low.humidity_too_low", {})
    assert _context_payload(
        pressure_result,
        weather(pressure=1010.0),
        peak_altitude=1500,
    ) == ("score.context.low.pressure_too_low", {})
    assert _context_payload(
        cloud_base_result,
        weather(cloud_base=1450),
        peak_altitude=1500,
    ) == ("score.context.low.cloud_base_too_high", {})
    assert _context_payload(
        fallback_result,
        weather(humidity=75.0, month=10),
        peak_altitude=1500,
    ) == ("score.context.low.conditions_too_marginal", {})

    sunny_clear_result = cast(
        ScoreResult,
        {
            "score": 10,
            "verdict": "low",
            "cloud_base": 900,
            "conditions": cast(
                ScoreConditions,
                {
                    "cloud_base_score": 0.6,
                    "humidity_score": 0.1,
                    "wind_score": 0.7,
                    "inversion_score": 0.8,
                    "pressure_score": 0.5,
                },
            ),
        },
    )

    assert _context_payload(
        sunny_clear_result,
        weather(humidity=75.0, month=7),
        peak_altitude=1500,
    ) == ("score.context.low.sunny_clear", {"clear_sky_altitude_m": 2400})


def test_optimal_window_branches() -> None:
    assert _optimal_window_from_sunrise(360, 18) == ("05:45", "07:00")
    assert _optimal_window_from_sunrise(360, 8) == ("05:50", "06:45")
    assert _optimal_window_from_sunrise(None, 18) == (None, None)
