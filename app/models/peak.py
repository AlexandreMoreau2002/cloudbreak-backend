"""Modèle SQLAlchemy — table peaks."""

from app.db.session import Base
from sqlalchemy import Column, Float, Integer, String


class Peak(Base):
    __tablename__ = "peaks"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    altitude = Column(Integer, nullable=False)
