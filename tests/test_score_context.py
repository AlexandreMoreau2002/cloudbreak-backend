from app.domain.score_context import _format_minutes, get_score_label_code


def test_get_score_label_code_handles_known_and_unknown_verdicts() -> None:
    assert get_score_label_code("high") == "score.label.high"
    assert get_score_label_code("medium") == "score.label.medium"
    assert get_score_label_code("unknown") == "score.label.none"


def test_format_minutes_normalizes_wraparound() -> None:
    assert _format_minutes(90) == "01:30"
    assert _format_minutes(24 * 60 + 5) == "00:05"
