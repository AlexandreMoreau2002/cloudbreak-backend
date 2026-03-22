"""Schémas Pydantic v2 — peaks."""

from pydantic import BaseModel


class PeakSearchResult(BaseModel):
    id: str
    name: str
    slug: str
    altitude: int


class PeakResponse(BaseModel):
    id: str
    name: str
    slug: str
    lat: float
    lng: float
    altitude: int
