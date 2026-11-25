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
from dataclasses import dataclass
from typing import Annotated, Any
from datetime import UTC, date as date_type, datetime, timedelta

from sqlalchemy import select
from redis.asyncio import Redis
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.models.peak import Peak
from app.db.session import get_db
from app.core.config import settings
from app.services.analytics import track
from app.core.errors import ApiError, ErrorCode
from app.services.weather import WeatherService
from app.models.prediction import Prediction
from app.domain.weather_types import WeatherData
from app.core.dependencies import check_quota, get_current_user, get_redis
from app.services.rate_limit import RateLimitExceededException, RateLimitService
from app.services.weather_providers.open_meteo import OpenMeteoProvider
from app.domain.score import (
    ScorePresentation,
    ScoreResult,
    build_score_presentation,
    calculate_score,
)
from app.schemas.score import (
    ScoreConditionsSchema,
    ScoreCloudLayerVizSchema,
    PressureLevelSchema,
    ScoreResponse,
    WeekScoreResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["score"])

# Instance partagée — provider + service météo
# Le provider et le service sont des singletons légers (pas d'état mutable)
_provider = OpenMeteoProvider()
_redis = aioredis.from_url(settings.redis_url, decode_responses=False)  # type: ignore[no-untyped-call]
weather_service = WeatherService(redis=_redis, provider=_provider)
WEEK_HOURS = (6, 8, 10, 12, 14, 16, 18, 20, 22)


def _optional_region(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _build_score_response(
    result: ScoreResult,
    weather: WeatherData,
    peak: Peak,
    presentation: ScorePresentation,
    prediction_id: str,
) -> ScoreResponse:
    """Construit le contrat score partagé par les endpoints simple et hebdomadaire."""
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


async def get_peak_by_id(peak_id: str, db: AsyncSession) -> Peak | None:
    """Récupère un sommet par son id en base de données."""
    result = await db.execute(select(Peak).where(Peak.id == peak_id))
    return result.scalar_one_or_none()


@dataclass(frozen=True)
class WeekScoreParams:
    """Entrées validées avant de laisser le quota muter Redis."""

    peak_id: str
    start_date: date_type
    peak: Peak


async def get_week_score_params(
    peak_id: Annotated[str, Query(description="Identifiant du sommet")],
    start_date: Annotated[date_type, Query(description="Premier jour ISO 8601")],
    db: AsyncSession = Depends(get_db),
) -> WeekScoreParams:
    """Valide la fenêtre UI en UTC et le sommet avant toute mutation Redis."""
    # La sélection mobile est centrée sur aujourd'hui ; ±1 jour absorbe le décalage de minuit
    # entre appareil et serveur sans ouvrir l'endpoint à des prévisions arbitraires.
    today_utc = datetime.now(UTC).date()
    if not today_utc - timedelta(days=1) <= start_date <= today_utc + timedelta(days=1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"detail": "start_date hors fenêtre", "code": "VALIDATION_ERROR"},
        )

    peak = await get_peak_by_id(peak_id, db)
    if not peak:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Sommet introuvable", "code": ErrorCode.PEAK_NOT_FOUND},
        )
    return WeekScoreParams(peak_id=peak_id, start_date=start_date, peak=peak)


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

    return _build_score_response(
        result=result,
        weather=weather,
        peak=peak,
        presentation=presentation,
        prediction_id=prediction_id,
    )


@router.get("/score/week", response_model=WeekScoreResponse)
async def get_score_week(
    request: Request,
    week_params: Annotated[WeekScoreParams, Depends(get_week_score_params)],
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    redis: Annotated[Redis, Depends(get_redis)],
    db: AsyncSession = Depends(get_db),
) -> WeekScoreResponse:
    """Calcule les 63 cellules après validation, rate-limit et quota explicites."""
    peak_id = week_params.peak_id
    peak = week_params.peak
    start_date_iso = week_params.start_date.isoformat()
    week_dates = [
        (week_params.start_date + timedelta(days=offset)).isoformat() for offset in range(7)
    ]
    try:
        await RateLimitService(redis).check_score_week(str(current_user["id"]))
    except RateLimitExceededException:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de requêtes",
            ErrorCode.RATE_LIMIT_EXCEEDED,
        ) from None

    current_user = await check_quota(
        request=request,
        user=current_user,
        redis=redis,
        db=db,
    )
    try:
        weather_week = await weather_service.get_week_forecast(
            lat=float(peak.lat),
            lng=float(peak.lng),
            start_date=start_date_iso,
            hours=WEEK_HOURS,
        )
        weather_cells = {
            (forecast_date, hour): weather_week[forecast_date][hour]
            for forecast_date in week_dates
            for hour in WEEK_HOURS
        }
    except Exception as exc:
        logger.error(
            "weather_week_provider_failed",
            extra={"peak_id": peak_id, "start_date": start_date_iso, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Données météo indisponibles", "code": ErrorCode.WEATHER_UNAVAILABLE},
        ) from exc

    predictions: list[Prediction] = []
    responses: dict[str, dict[int, ScoreResponse]] = {}
    for forecast_date in week_dates:
        responses[forecast_date] = {}
        for hour in WEEK_HOURS:
            weather = weather_cells[(forecast_date, hour)]
            result = calculate_score(weather, peak_altitude=int(peak.altitude))
            presentation = build_score_presentation(
                result=result,
                weather=weather,
                date=forecast_date,
                lat=float(peak.lat),
                lng=float(peak.lng),
                peak_altitude=int(peak.altitude),
            )
            prediction_id = uuid.uuid4()
            prediction_id_string = str(prediction_id)
            predictions.append(
                Prediction(
                    id=prediction_id,
                    peak_id=peak_id,
                    user_id=str(current_user["id"]),
                    date=forecast_date,
                    hour=hour,
                    score=result["score"],
                    verdict=result["verdict"],
                    cloud_base=result["cloud_base"],
                    created_at=datetime.now(UTC),
                )
            )
            responses[forecast_date][hour] = _build_score_response(
                result=result,
                weather=weather,
                peak=peak,
                presentation=presentation,
                prediction_id=prediction_id_string,
            )

    try:
        db.add_all(predictions)
        await db.commit()
    except Exception as exc:
        logger.error(
            "prediction_week_persist_failed",
            extra={"peak_id": peak_id, "start_date": start_date_iso, "error": str(exc)},
        )
        try:
            await db.rollback()
        except Exception as rollback_exc:
            logger.error(
                "prediction_week_rollback_failed",
                extra={"peak_id": peak_id, "error": str(rollback_exc)},
            )

    logger.info(
        "score_week_calculated",
        extra={"peak_id": peak_id, "start_date": start_date_iso, "cell_count": len(predictions)},
    )
    track(
        "score_week_calculated",
        str(current_user["id"]),
        {
            "peak_id": peak_id,
            "cell_count": len(predictions),
            "plan": current_user.get("plan", "free"),
        },
    )
    return WeekScoreResponse(by_date=responses)
