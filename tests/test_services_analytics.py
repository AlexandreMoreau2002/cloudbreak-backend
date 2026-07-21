"""Tests du stub analytics — log DEBUG uniquement, jamais d'exception."""

import logging

from app.services.analytics import track


def test_track_ne_leve_pas_avec_properties(caplog: object) -> None:
    with_caplog = caplog  # type: ignore[assignment]
    with_caplog.set_level(logging.DEBUG, logger="app.services.analytics")  # type: ignore[attr-defined]
    track("score_calculated", "user-123", {"peak_id": "peak-1", "verdict": "high"})
    assert any(
        record.message == "analytics_event"
        and record.event == "score_calculated"  # type: ignore[attr-defined]
        and record.user_id == "user-123"  # type: ignore[attr-defined]
        for record in with_caplog.records  # type: ignore[attr-defined]
    )


def test_track_sans_properties_ne_leve_pas() -> None:
    track("account_deleted", "user-456")
