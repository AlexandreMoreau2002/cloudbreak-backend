"""Tests du modèle TerrainValidation."""

import uuid
from datetime import UTC, datetime

from app.models.terrain_validation import TerrainValidation


def test_terrain_validation_a_les_champs_attendus() -> None:
    val = TerrainValidation(
        id=uuid.uuid4(),
        prediction_id=uuid.uuid4(),
        user_id="user-123",
        result=True,
        photo_url=None,
        lat=45.83,
        lng=6.86,
        validated_at=datetime.now(UTC),
    )
    assert val.user_id == "user-123"
    assert val.result is True
    assert val.photo_url is None
    assert val.lat == 45.83
    assert val.lng == 6.86


def test_terrain_validation_tablename() -> None:
    assert TerrainValidation.__tablename__ == "terrain_validations"
