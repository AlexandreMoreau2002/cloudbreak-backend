"""Service de suppression des données utilisateur (RGPD)."""

import logging
from datetime import UTC, datetime
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.terrain_validation import TerrainValidation
from app.models.user import User
from app.schemas.user import SurveyUpdate

logger = logging.getLogger(__name__)


async def delete_user_data(user_id: str, db: AsyncSession) -> None:
    """Supprime toutes les données locales d'un utilisateur.

    Ordre : terrain_validations d'abord (supprimées explicitement par user_id,
    y compris si elles référencent la prédiction d'un autre utilisateur — cas
    résiduel possible sur des données antérieures au correctif d'ownership de
    l'endpoint POST /api/v1/validations), puis predictions (le
    ondelete="CASCADE" de terrain_validations.prediction_id supprimera au
    passage toute validation résiduelle du même utilisateur), puis favoris,
    puis subscription. La table `events` n'existe pas encore et reste ignorée
    silencieusement.

    Args:
        user_id: ID utilisateur Supabase (UUID string)
        db: Session SQLAlchemy async
    """
    await db.execute(delete(TerrainValidation).where(TerrainValidation.user_id == user_id))
    await db.execute(delete(Prediction).where(Prediction.user_id == user_id))
    await db.execute(delete(Favorite).where(Favorite.user_id == user_id))
    await db.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await db.execute(delete(User).where(User.supabase_user_id == user_id))
    await db.commit()
    logger.debug(
        "user_data_deleted",
        extra={"user_id": user_id},
    )


async def get_or_create_user(user_id: str, auth_provider: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.supabase_user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        await db.execute(
            insert(User)
            .values(supabase_user_id=user_id, auth_provider=auth_provider)
            .on_conflict_do_nothing(index_elements=[User.supabase_user_id])
        )
        result = await db.execute(select(User).where(User.supabase_user_id == user_id))
        user = result.scalar_one()
    return user


async def get_user_profile(user_id: str, db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.supabase_user_id == user_id))
    return result.scalar_one_or_none()


async def provision_user(user: dict[str, object], db: AsyncSession) -> User:
    return await get_or_create_user(str(user["id"]), str(user.get("auth_provider", "email")), db)


async def update_user_survey(
    user: dict[str, object], survey: SurveyUpdate, db: AsyncSession
) -> User:
    profile = await get_or_create_user(str(user["id"]), str(user.get("auth_provider", "email")), db)
    if profile.survey_completed_at is not None or profile.survey_skipped_at is not None:
        return profile
    if survey.skipped:
        profile.survey_skipped_at = datetime.now(UTC)
    else:
        profile.acquisition_source = (
            survey.acquisition_source.value if survey.acquisition_source else None
        )
        profile.practice = survey.practice.value if survey.practice else None
        profile.newsletter_opt_in = survey.newsletter_opt_in
        profile.survey_completed_at = datetime.now(UTC)
    await db.flush()
    return profile
