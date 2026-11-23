from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String

from app.db.session import Base


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    id = Column(String(36), primary_key=True)
    actor_id = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    resource = Column(String(100), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    result = Column(String(20), nullable=False)
