from app.domain.score_components import (
    CLOUD_COVER_LOW_BLOCKING_THRESHOLD,
    HIGH_MIN_LOW_CLOUD_COVER,
    _zero_conditions,
)


def test_cloud_cover_thresholds_match_product_decision() -> None:
    assert CLOUD_COVER_LOW_BLOCKING_THRESHOLD == 45.0
    assert HIGH_MIN_LOW_CLOUD_COVER == 55.0


def test_zero_conditions_returns_all_components_to_zero() -> None:
    assert _zero_conditions() == {
        "cloud_base_score": 0.0,
        "humidity_score": 0.0,
        "wind_score": 0.0,
        "inversion_score": 0.0,
        "pressure_score": 0.0,
    }
