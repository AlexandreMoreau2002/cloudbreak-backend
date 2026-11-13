"""Schémas Pydantic v2 — favoris."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.peak import PeakSearchResult


class FavoriteCreate(BaseModel):
    peak_id: str


class FavoriteResponse(BaseModel):
    id: str
    peak_id: str
    peak: PeakSearchResult
    created_at: datetime
