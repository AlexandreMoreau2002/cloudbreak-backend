from app.domain.score_context import _optimal_window_from_sunrise


def test_optimal_window_from_sunrise_uses_mid_tier_offsets() -> None:
    assert _optimal_window_from_sunrise(600, 18) == ("09:45", "11:00")
    assert _optimal_window_from_sunrise(600, 35) == ("09:45", "11:00")


def test_optimal_window_from_sunrise_uses_short_tier_offsets() -> None:
    assert _optimal_window_from_sunrise(600, 17) == ("09:50", "10:45")
    assert _optimal_window_from_sunrise(5, 0) == ("23:55", "00:50")
