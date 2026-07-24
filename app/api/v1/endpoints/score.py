"""
Endpoint GET /api/v1/score

Paramètres :
  peak_id : str  — identifiant du sommet
  date    : str  — date ISO 8601 (ex: "2026-10-15")
  hour    : int  — heure souhaitée (0-23, optionnel, défaut 6h)

Flux :
  1. JWT validé par get_current_user (dependency)
  2. Sommet récupéré en DB
  3. Données météo récupérées via WeatherService (cache Redis + provider)
  4. Score calculé par calculate_score()
  5. Réponse retournée directement (pas de wrapper)

Erreurs :
  404 PEAK_NOT_FOUND       — sommet inconnu
  503 WEATHER_UNAVAILABLE  — provider météo indisponible
"""

import uuid
import logging
from sqlalchemy import select
import redis.asyncio as aioredis
from typing import Annotated, Any
from datetime import UTC, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.models.peak import Peak
from app.db.session import get_db
from app.core.config import settings
from app.core.errors import ErrorCode
from app.services.analytics import track
from app.models.prediction import Prediction
from app.core.dependencies import check_quota
from app.services.weather import WeatherService
from app.domain.score import build_score_presentation, calculate_score
from app.services.weather_providers.open_meteo import OpenMeteoProvider
from app.schemas.score import (
    ScoreConditionsSchema,
    ScoreCloudLayerVizSchema,
    PressureLevelSchema,
    ScoreResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["score"])

# Instance partagée — provider + service météo
# Le provider et le service sont des singletons légers (pas d'état mutable)
_provider = OpenMeteoProvider()
_redis = aioredis.from_url(settings.redis_url, decode_responses=False)  # type: ignore[no-untyped-call]
weather_service = WeatherService(redis=_redis, provider=_provider)


def _optional_region(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def get_peak_by_id(peak_id: str, db: AsyncSession) -> Peak | None:
    """Récupère un sommet par son id en base de données."""
    result = await db.execute(select(Peak).where(Peak.id == peak_id))
    return result.scalar_one_or_none()


@router.get("/score", response_model=ScoreResponse)
async def get_score(
    peak_id: Annotated[str, Query(description="Identifiant du sommet")],
    date: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date ISO 8601")],
    hour: Annotated[int, Query(ge=0, le=23, description="Heure souhaitée (défaut: 6h)")] = 6,
    current_user: dict[str, Any] = Depends(check_quota),
    db: AsyncSession = Depends(get_db),
) -> ScoreResponse:
    peak = await get_peak_by_id(peak_id, db)
    if not peak:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Sommet introuvable", "code": ErrorCode.PEAK_NOT_FOUND},
        )

    try:
        weather = await weather_service.get_forecast(
            lat=float(peak.lat), lng=float(peak.lng), date=date, hour=hour
        )
    except Exception as exc:
        logger.error(
            "weather_provider_failed",
            extra={"peak_id": peak_id, "date": date, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Données météo indisponibles", "code": ErrorCode.WEATHER_UNAVAILABLE},
        ) from exc

    result = calculate_score(weather, peak_altitude=int(peak.altitude))
    presentation = build_score_presentation(
        result=result,
        weather=weather,
        date=date,
        lat=float(peak.lat),
        lng=float(peak.lng),
        peak_altitude=int(peak.altitude),
    )
    logger.info(
        "score_calculated",
        extra={
            "peak_id": peak_id,
            "date": date,
            "score": result["score"],
            "verdict": result["verdict"],
        },
    )
    track(
        "score_calculated",
        str(current_user["id"]),
        {
            "peak_id": peak_id,
            "verdict": result["verdict"],
            "score": result["score"],
            "plan": current_user.get("plan", "free"),
        },
    )

    prediction = Prediction(
        id=uuid.uuid4(),
        peak_id=peak_id,
        user_id=str(current_user["id"]),
        date=date,
        hour=hour,
        score=result["score"],
        verdict=result["verdict"],
        cloud_base=result["cloud_base"],
        created_at=datetime.now(UTC),
    )
    try:
        db.add(prediction)
        await db.commit()
        await db.refresh(prediction)
        prediction_id = str(prediction.id)
    except Exception as exc:
        logger.error("prediction_persist_failed", extra={"peak_id": peak_id, "error": str(exc)})
        # id éphémère — une validation terrain le référençant échouera proprement en 404
        prediction_id = str(uuid.uuid4())

    cond = result["conditions"]
    return ScoreResponse(
        score=result["score"],
        verdict=result["verdict"],
        label_code=presentation["label_code"],
        context_code=presentation["context_code"],
        context_params=presentation["context_params"],
        cloud_base=result["cloud_base"],
        peak_slug=str(peak.slug),
        prediction_id=prediction_id,
        optimal_window_start=presentation["optimal_window_start"],
        optimal_window_end=presentation["optimal_window_end"],
        sunrise=presentation["sunrise"],
        stability_hours=presentation["stability_hours"],
        conditions=ScoreConditionsSchema(
            cloud_base_score=cond["cloud_base_score"],
            humidity_score=cond["humidity_score"],
            wind_score=cond["wind_score"],
            inversion_score=cond["inversion_score"],
            pressure_score=cond["pressure_score"],
            cloud_base_m=result["cloud_base"],
            humidity_pct=float(weather.humidity),
            wind_speed_kmh=float(weather.wind_speed),
            inversion_delta_c=float(weather.temperature_850hpa - weather.temperature_925hpa),
            inversion_detected=bool(weather.temperature_850hpa > weather.temperature_925hpa),
            pressure_hpa=float(weather.pressure),
            cloud_cover_low_pct=float(weather.cloud_cover_low),
        ),
        cloud_layer_viz=ScoreCloudLayerVizSchema(
            summit_altitude=int(peak.altitude),
            cloud_base=result["cloud_base"],
            pressure_levels=[
                PressureLevelSchema(
                    pressure_hpa=level.pressure_hpa,
                    altitude_m=level.altitude_m,
                    temperature_c=level.temperature_c,
                    relative_humidity=level.relative_humidity,
                    dew_point_spread=level.dew_point_spread,
                )
                for level in weather.pressure_levels
            ],
        ),
        peak_name=str(peak.name),
        peak_altitude=int(peak.altitude),
        peak_region=_optional_region(peak.region),
    )
