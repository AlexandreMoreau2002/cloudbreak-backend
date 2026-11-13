"""Tests du modèle Prediction."""

import uuid
from datetime import UTC, datetime

from app.models.prediction import Prediction


def test_prediction_a_les_champs_attendus() -> None:
    pred = Prediction(
        id=uuid.uuid4(),
        peak_id="peak-1",
        user_id="user-123",
        date="2026-07-24",
        hour=6,
        score=82,
        verdict="high",
        cloud_base=1800,
        created_at=datetime.now(UTC),
    )
    assert pred.peak_id == "peak-1"
    assert pred.user_id == "user-123"
    assert pred.hour == 6
    assert pred.score == 82
    assert pred.verdict == "high"
    assert pred.cloud_base == 1800


def test_prediction_tablename() -> None:
    assert Prediction.__tablename__ == "predictions"
