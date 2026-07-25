"""Schémas Pydantic v2 — validation terrain (story 6.1)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class TerrainValidationCreate(BaseModel):
    prediction_id: uuid.UUID
    result: bool
    lat: float | None = None
    lng: float | None = None


class TerrainValidationResponse(BaseModel):
    id: str
    prediction_id: str
    user_id: str
    result: bool
    photo_url: str | None
    lat: float | None
    lng: float | None
    validated_at: datetime
