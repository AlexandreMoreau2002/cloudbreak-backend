import logging
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status
from app.db.session import get_db
from app.core.config import settings
from app.core.errors import ErrorCode
from app.services.analytics import track
from app.core.dependencies import get_current_user
from app.core.security import delete_supabase_user
from app.schemas.user import SurveyUpdate, UserProfile
from app.services.user import delete_user_data, get_user_profile, provision_user, update_user_survey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user", tags=["user"])


@router.get("/me")
async def get_me(
    current_user: dict[str, object] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    profile = None
    if not bool(current_user.get("is_anonymous", False)):
        profile = await get_user_profile(str(current_user["id"]), db)
    return {
        **current_user,
        "is_anonymous": bool(current_user.get("is_anonymous", False)),
        "provisioned": profile is not None,
        "survey_completed_at": profile.survey_completed_at if profile else None,
        "survey_skipped_at": profile.survey_skipped_at if profile else None,
    }


def _require_permanent(current_user: dict[str, object]) -> None:
    if bool(current_user.get("is_anonymous", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "Un compte permanent est requis", "code": ErrorCode.ACCOUNT_REQUIRED},
        )


@router.post("/provision", response_model=UserProfile)
async def provision(
    current_user: dict[str, object] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    _require_permanent(current_user)
    profile = await provision_user(current_user, db)
    await db.commit()
    return profile


@router.patch("/survey", response_model=UserProfile)
async def survey(
    payload: SurveyUpdate,
    current_user: dict[str, object] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    _require_permanent(current_user)
    profile = await update_user_survey(current_user, payload, db)
    await db.commit()
    return profile


@router.delete("", status_code=204)
async def delete_user(
    current_user: dict[str, object] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Supprime le compte utilisateur et toutes ses données (RGPD).

    Ordre : données DB en premier, compte Supabase ensuite.
    Retourne 204 No Content en cas de succès.
    """
    user_id = str(current_user["id"])
    await delete_user_data(user_id, db)
    await delete_supabase_user(user_id, settings.supabase_url, settings.supabase_service_role_key)
    logger.info("user_deleted", extra={"user_id": user_id})
    track("account_deleted", user_id)
