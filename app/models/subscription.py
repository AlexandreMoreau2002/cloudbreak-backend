"""Subscription — Modèle utilisateur Premium/Pro."""

from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Subscription(Base):
    """Enregistrement d'abonnement utilisateur."""

    __tablename__ = "subscriptions"

    user_id = Column(String(255), primary_key=True)  # UUID Supabase
    plan = Column(String(50), default="free")  # free | premium | pro
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Subscription user_id={self.user_id} plan={self.plan}>"
