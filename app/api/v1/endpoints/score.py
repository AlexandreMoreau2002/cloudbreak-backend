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

import logging
from sqlalchemy import select
import redis.asyncio as aioredis
from app.models.peak import Peak
from app.db.session import get_db
from typing import Annotated, Any
from app.core.config import settings
from app.core.errors import ErrorCode
from app.services.score import calculate_score
from app.services.weather import WeatherService
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user
from app.schemas.score import ScoreConditionsSchema, ScoreResponse
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.services.weather_providers.open_meteo import OpenMeteoProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["score"])

# Instance partagée — provider + service météo
# Le provider et le service sont des singletons légers (pas d'état mutable)
_provider = OpenMeteoProvider()
_redis = aioredis.from_url(settings.redis_url, decode_responses=False)  # type: ignore[no-untyped-call]
weather_service = WeatherService(redis=_redis, provider=_provider)


async def get_peak_by_id(peak_id: str, db: AsyncSession) -> Peak | None:
    """Récupère un sommet par son id en base de données."""
    result = await db.execute(select(Peak).where(Peak.id == peak_id))
    return result.scalar_one_or_none()


@router.get("/score", response_model=ScoreResponse)
async def get_score(
    peak_id: Annotated[str, Query(description="Identifiant du sommet")],
    date: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date ISO 8601, ex: 2026-10-15")],
    hour: Annotated[int, Query(ge=0, le=23, description="Heure souhaitée (défaut: 6h)")] = 6,
    current_user: dict[str, Any] = Depends(get_current_user),
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

    logger.info(
        "score_calculated",
        extra={
            "peak_id": peak_id,
            "date": date,
            "score": result["score"],
            "verdict": result["verdict"],
        },
    )

    cond = result["conditions"]
    return ScoreResponse(
        score=result["score"],
        verdict=result["verdict"],
        cloud_base=result["cloud_base"],
        conditions=ScoreConditionsSchema(
            cloud_base_score=cond["cloud_base_score"],
            humidity_score=cond["humidity_score"],
            wind_score=cond["wind_score"],
            inversion_score=cond["inversion_score"],
            pressure_score=cond["pressure_score"],
        ),
        peak_name=str(peak.name),
        peak_altitude=int(peak.altitude),
    )
