"""Schémas Pydantic v2 — endpoint score."""

from pydantic import BaseModel, Field


class ScoreConditionsSchema(BaseModel):
    cloud_base_score: float = Field(description="Composante cloud_base (0.0-1.0)")
    humidity_score: float = Field(description="Composante humidité (0.0-1.0)")
    wind_score: float = Field(description="Composante vent (0.0-1.0)")
    inversion_score: float = Field(description="Composante inversion thermique (0.0-1.0)")
    pressure_score: float = Field(description="Composante pression atmosphérique (0.0-1.0)")


class ScoreResponse(BaseModel):
    score: int = Field(ge=0, le=100, description="Score de probabilité en %")
    verdict: str = Field(description="none | high | medium | low")
    cloud_base: int = Field(description="Altitude de la base des nuages en mètres")
    conditions: ScoreConditionsSchema
    peak_name: str
    peak_altitude: int
