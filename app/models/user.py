"""Profil applicatif lié à une identité Supabase permanente."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, String, true

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    supabase_user_id = Column(String(255), primary_key=True)
    auth_provider = Column(String(50), nullable=False)
    # Copie de l'email Supabase (claim du JWT) pour relier une ligne à un compte lisible.
    # Null pour les comptes sans email et les lignes antérieures, rempli au prochain appel.
    email = Column(String(320), nullable=True)
    display_name = Column(String(24), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    converted_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    survey_completed_at = Column(DateTime(timezone=True), nullable=True)
    survey_skipped_at = Column(DateTime(timezone=True), nullable=True)
    acquisition_source = Column(String(50), nullable=True)
    practice = Column(String(50), nullable=True)
    newsletter_opt_in = Column(Boolean, nullable=True)
    notif_favorites = Column(Boolean, nullable=False, server_default=true())
    notif_regional = Column(Boolean, nullable=False, server_default=true())
    notif_terrain = Column(Boolean, nullable=False, server_default=true())

    # Token Expo Push de l'appareil courant (un seul appareil par compte).
    # Jamais exposé par l'API ni loggué. `push_token_valid` passe à false quand
    # Expo répond DeviceNotRegistered ; un nouvel enregistrement le remet à true.
    push_token = Column(String(255), nullable=True)
    push_token_valid = Column(Boolean, nullable=False, server_default=true())
