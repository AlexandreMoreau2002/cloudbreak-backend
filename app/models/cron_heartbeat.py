from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String

from app.db.session import Base


class CronHeartbeat(Base):
    __tablename__ = "cron_heartbeats"
    job = Column(String(20), primary_key=True)
    last_run_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    last_status = Column(String(10), nullable=False)
    last_ok_at = Column(DateTime(timezone=True), nullable=True)
