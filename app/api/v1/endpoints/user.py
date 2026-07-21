import logging
from app.db.session import get_db
from app.core.config import settings
from fastapi import APIRouter, Depends
from app.services.analytics import track
from app.services.user import delete_user_data
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user
from app.core.security import delete_supabase_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user", tags=["user"])


@router.get("/me")
def get_me(current_user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    return current_user


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
