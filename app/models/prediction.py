"""Modèle SQLAlchemy — table predictions.

Une ligne est écrite à chaque calcul de score réussi (GET /api/v1/score),
best-effort — voir app/api/v1/endpoints/score.py. Sert de référence pour
terrain_validations.prediction_id (story 6.1).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.session import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    peak_id = Column(String, ForeignKey("peaks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    date = Column(String, nullable=False)
    hour = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    verdict = Column(String, nullable=False)
    cloud_base = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
