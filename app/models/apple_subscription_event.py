"""Idempotency ledger for App Store Server Notification V2 events."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String

from app.db.session import Base


class AppleSubscriptionEvent(Base):
    """A processed Apple lifecycle notification, keyed by Apple's UUID."""

    __tablename__ = "apple_subscription_events"

    notification_uuid = Column(String(255), primary_key=True)
    notification_type = Column(String(100), nullable=False)
    original_transaction_id = Column(String(255), nullable=True)
    signed_date = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AppleSubscriptionEvent notification_type={self.notification_type}>"
