"""
Endpoint validation terrain.

  POST /api/v1/validations — confirmer/infirmer une prédiction depuis le terrain

Auth required. 404 si prediction_id inconnu.
"""

import uuid
import logging
from typing import Any
from sqlalchemy import select
from app.db.session import get_db
from app.core.errors import ErrorCode
from app.services.analytics import track
from app.models.prediction import Prediction
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user
from app.models.terrain_validation import TerrainValidation
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.validation import TerrainValidationCreate, TerrainValidationResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["validations"])


@router.post(
    "/validations", response_model=TerrainValidationResponse, status_code=status.HTTP_201_CREATED
)
async def create_validation(
    body: TerrainValidationCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TerrainValidationResponse:
    """Enregistre une validation terrain (confirmation/infirmation)."""
    user_id = str(current_user["id"])

    pred_result = await db.execute(select(Prediction).where(Prediction.id == body.prediction_id))
    prediction = pred_result.scalar_one_or_none()
    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Prédiction introuvable", "code": ErrorCode.NOT_FOUND},
        )

    validation = TerrainValidation(
        id=uuid.uuid4(),
        prediction_id=body.prediction_id,
        user_id=user_id,
        result=body.result,
        photo_url=None,
        lat=body.lat,
        lng=body.lng,
    )
    db.add(validation)
    await db.commit()
    await db.refresh(validation)

    logger.info(
        "terrain_validated",
        extra={"user_id": user_id, "prediction_id": body.prediction_id, "result": body.result},
    )
    track(
        "terrain_validated",
        user_id,
        {"prediction_id": body.prediction_id, "result": body.result},
    )

    return TerrainValidationResponse(
        id=str(validation.id),
        prediction_id=str(validation.prediction_id),
        user_id=str(validation.user_id),
        result=bool(validation.result),
        photo_url=None,
        lat=validation.lat,  # type: ignore[arg-type]
        lng=validation.lng,  # type: ignore[arg-type]
        validated_at=validation.validated_at,  # type: ignore[arg-type]
    )
