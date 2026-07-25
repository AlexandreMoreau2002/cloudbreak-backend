"""Modèle SQLAlchemy — table terrain_validations (story 6.1).

photo_url reste toujours null tant que la story 6.2 (upload photo) n'est
pas implémentée — colonne présente dès maintenant pour éviter une migration
supplémentaire plus tard.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.session import Base


class TerrainValidation(Base):
    __tablename__ = "terrain_validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String, nullable=False, index=True)
    result = Column(Boolean, nullable=False)
    photo_url = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    validated_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
