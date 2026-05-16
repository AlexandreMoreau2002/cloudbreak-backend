"""Service de suppression des données utilisateur (RGPD)."""

import logging
from sqlalchemy import delete
from app.models.favorite import Favorite
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


async def delete_user_data(user_id: str, db: AsyncSession) -> None:
    """Supprime toutes les données locales d'un utilisateur.

    Ordre : favoris d'abord, subscription ensuite.
    Les tables non encore créées (predictions, terrain_validations, events)
    sont ignorées silencieusement.

    Args:
        user_id: ID utilisateur Supabase (UUID string)
        db: Session SQLAlchemy async
    """
    await db.execute(delete(Favorite).where(Favorite.user_id == user_id))
    await db.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await db.commit()
    logger.debug(
        "user_data_deleted",
        extra={"user_id": user_id},
    )
