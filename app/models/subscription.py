"""Subscription — Modèle utilisateur Premium/Pro."""

from app.db.session import Base
from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, String


class Subscription(Base):
    """Enregistrement d'abonnement utilisateur."""

    __tablename__ = "subscriptions"

    user_id = Column(String(255), primary_key=True)  # UUID Supabase
    plan = Column(String(50), default="free")  # free | premium | pro
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<Subscription user_id={self.user_id} plan={self.plan}>"
