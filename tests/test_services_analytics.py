"""Tests de l'adaptateur analytics — jamais d'exception sans configuration."""

from app.services import analytics


def test_track_ne_leve_pas_avec_properties_sans_configuration(monkeypatch) -> None:
    monkeypatch.setattr(analytics, "_client", None)

    analytics.track("score_calculated", "user-123", {"peak_id": "peak-1", "verdict": "high"})


def test_track_sans_properties_ne_leve_pas(monkeypatch) -> None:
    monkeypatch.setattr(analytics, "_client", None)

    analytics.track("account_deleted", "user-456")
