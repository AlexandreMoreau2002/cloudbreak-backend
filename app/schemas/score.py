"""Schémas Pydantic v2 — endpoint score."""

from pydantic import BaseModel, Field


class PressureLevelSchema(BaseModel):
    pressure_hpa: int = Field(description="Niveau de pression en hPa")
    altitude_m: int = Field(description="Altitude MSL du niveau en mètres")
    temperature_c: float = Field(description="Température au niveau de pression en °C")
    relative_humidity: float = Field(description="Humidité relative au niveau de pression (%)")
    dew_point_spread: float = Field(description="Écart température/point de rosée en °C")


class ScoreCloudLayerVizSchema(BaseModel):
    summit_altitude: int = Field(description="Altitude du sommet en mètres")
    cloud_base: int = Field(description="Altitude de la base des nuages en mètres")
    pressure_levels: list[PressureLevelSchema] = Field(
        default_factory=list,
        description="Profil vertical utilisé pour le diagramme couche/sommet",
    )


class ScoreConditionsSchema(BaseModel):
    cloud_base_score: float = Field(description="Composante cloud_base (0.0-1.0)")
    humidity_score: float = Field(description="Composante humidité (0.0-1.0)")
    wind_score: float = Field(description="Composante vent (0.0-1.0)")
    inversion_score: float = Field(description="Composante inversion thermique (0.0-1.0)")
    pressure_score: float = Field(description="Composante pression atmosphérique (0.0-1.0)")
    cloud_base_m: int = Field(description="Altitude réelle de la base des nuages en mètres")
    humidity_pct: float = Field(description="Humidité relative 2m en %")
    wind_speed_kmh: float = Field(description="Vitesse du vent 10m en km/h")
    inversion_delta_c: float = Field(description="Delta T 850hPa - 925hPa en °C")
    inversion_detected: bool = Field(description="Inversion thermique détectée")
    pressure_hpa: float = Field(description="Pression de surface en hPa")
    cloud_cover_low_pct: float = Field(description="Couverture nuageuse basse en %")


class ScoreResponse(BaseModel):
    score: int = Field(ge=0, le=100, description="Score de probabilité en %")
    verdict: str = Field(description="none | high | medium | low")
    label_code: str = Field(description="Clé i18n stable associée au verdict")
    context_code: str = Field(description="Clé i18n stable du message contextuel")
    context_params: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="Paramètres interpolables pour le message contextuel",
    )
    cloud_base: int = Field(description="Altitude de la base des nuages en mètres")
    peak_slug: str = Field(description="Slug du sommet pour le deep link")
    optimal_window_start: str | None = Field(
        default=None,
        description="Début de la fenêtre optimale (HH:MM local)",
    )
    optimal_window_end: str | None = Field(
        default=None,
        description="Fin de la fenêtre optimale (HH:MM local)",
    )
    sunrise: str | None = Field(
        default=None,
        description="Heure estimée du lever du soleil (HH:MM local)",
    )
    stability_hours: int = Field(description="Stabilité estimée de la prévision en heures")
    conditions: ScoreConditionsSchema
    cloud_layer_viz: ScoreCloudLayerVizSchema
    peak_name: str
    peak_altitude: int
    peak_region: str | None = None
