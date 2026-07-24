"""Service de suppression des données utilisateur (RGPD)."""

import logging
from sqlalchemy import delete
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.subscription import Subscription
from app.models.terrain_validation import TerrainValidation

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
    await db.commit()
    logger.debug(
        "user_data_deleted",
        extra={"user_id": user_id},
    )
