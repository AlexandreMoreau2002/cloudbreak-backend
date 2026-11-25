from sqlalchemy import Column, Date, Integer

from app.db.session import Base


class DailyStat(Base):
    """Instantané quotidien de compteurs (aucune donnée personnelle)."""

    __tablename__ = "daily_stats"
    day = Column(Date, primary_key=True)
    users_total = Column(Integer, nullable=False)
    accounts_total = Column(Integer, nullable=False)
    checks = Column(Integer, nullable=False)
