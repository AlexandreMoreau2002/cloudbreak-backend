"""Service de suppression des données utilisateur (RGPD)."""

import logging
from datetime import UTC, datetime
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.favorite import Favorite
from app.models.prediction import Prediction
from app.models.subscription import Subscription
from app.models.terrain_validation import TerrainValidation
from app.schemas.user import (
    DisplayNameUpdate,
    PreferencesUpdate,
    SurveyUpdate,
    NotificationPreferencesUpdate,
)

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


def _token_email(user: dict[str, object]) -> str | None:
    """Email du claim JWT, ou None (compte anonyme, claim absent ou invalide)."""
    email = user.get("email")
    return email if isinstance(email, str) and email else None


async def get_or_create_user(
    user_id: str, auth_provider: str, db: AsyncSession, email: str | None = None
) -> User:
    result = await db.execute(select(User).where(User.supabase_user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        await db.execute(
            insert(User)
            .values(supabase_user_id=user_id, auth_provider=auth_provider, email=email)
            .on_conflict_do_nothing(index_elements=[User.supabase_user_id])
        )
        result = await db.execute(select(User).where(User.supabase_user_id == user_id))
        user = result.scalar_one()
    elif email is not None and user.email != email:
        # Rattrape les lignes antérieures à la colonne et suit un changement d'email Supabase.
        # L'email n'est volontairement pas loggué (donnée personnelle).
        user.email = email  # type: ignore[assignment]
        await db.flush()
    return user


async def get_user_profile(user_id: str, db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.supabase_user_id == user_id))
    return result.scalar_one_or_none()


async def provision_user(user: dict[str, object], db: AsyncSession) -> User:
    return await get_or_create_user(
        str(user["id"]), str(user.get("auth_provider", "email")), db, _token_email(user)
    )


async def update_user_display_name(
    user: dict[str, object], payload: DisplayNameUpdate, db: AsyncSession
) -> User:
    profile = await get_or_create_user(
        str(user["id"]), str(user.get("auth_provider", "email")), db, _token_email(user)
    )
    profile.display_name = payload.display_name  # type: ignore[assignment]
    await db.flush()
    return profile


async def update_user_survey(
    user: dict[str, object], survey: SurveyUpdate, db: AsyncSession
) -> User:
    profile = await get_or_create_user(
        str(user["id"]), str(user.get("auth_provider", "email")), db, _token_email(user)
    )
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


async def update_user_preferences(
    user: dict[str, object], prefs: PreferencesUpdate, db: AsyncSession
) -> User:
    """Met à jour le consentement newsletter — toujours modifiable, dans les deux sens.

    Contrairement au sondage (`update_user_survey`), il n'y a pas de champ terminal :
    l'utilisateur peut retirer son consentement à tout moment (RGPD art. 7-3).
    """
    profile = await get_or_create_user(
        str(user["id"]), str(user.get("auth_provider", "email")), db, _token_email(user)
    )
    # mypy voit la colonne comme `Column[bool]` sur une affectation d'un `bool` nu
    # (friction stubs SQLAlchemy, cf. `favorites.py` / `validations.py`).
    profile.newsletter_opt_in = prefs.newsletter_opt_in  # type: ignore[assignment]
    await db.flush()
    return profile


async def update_user_notification_preferences(
    user: dict[str, object], prefs: NotificationPreferencesUpdate, db: AsyncSession
) -> User:
    """Met à jour une ou plusieurs préférences de notification — update partiel.

    Seuls les champs explicitement envoyés dans le payload sont modifiés (les autres
    préférences ne sont pas touchées) — contrairement à `update_user_preferences` qui
    n'a qu'un seul champ toujours requis.
    """
    profile = await get_or_create_user(
        str(user["id"]), str(user.get("auth_provider", "email")), db, _token_email(user)
    )
    for field, value in prefs.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.flush()
    return profile
