"""Purge des comptes anonymes inactifs (minimisation RGPD).

Une session Supabase anonyme laisse des données (`predictions`, `terrain_validations`,
`user_favorites`) que plus personne ne peut supprimer si la session est perdue. Ce job,
appelé par un cron, efface les identifiants sans activité depuis `retention_days` jours.

Double garde : seuls les identifiants sans ligne `users` sont candidats, et Supabase doit
confirmer `is_anonymous is True` (ou l'absence de l'utilisateur) avant toute suppression.
Aucun identifiant utilisateur n'est loggé ni renvoyé : uniquement des compteurs.
"""

import logging
from redis.asyncio import Redis
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Select, func, select, union_all

from app.models.user import User
from app.models.favorite import Favorite
from app.services.quota import QuotaService
from app.models.prediction import Prediction
from app.services.user import delete_user_data
from app.models.terrain_validation import TerrainValidation
from app.core.security import SupabaseAdminError, get_supabase_user, delete_supabase_user

logger = logging.getLogger(__name__)


@dataclass
class PurgeSummary:
    candidates: int = 0
    purged: int = 0
    skipped_not_anonymous: int = 0
    errors: int = 0
    dry_run: bool = False


def build_candidates_query(cutoff: datetime, max_per_run: int) -> Select[tuple[str]]:
    """user_id dont la dernière activité est antérieure à `cutoff`, sans ligne `users`.

    Une seule requête agrégée sur l'union des trois tables d'activité, les plus anciens
    d'abord, plafonnée à `max_per_run`.
    """
    activity = union_all(
        select(Prediction.user_id.label("user_id"), Prediction.created_at.label("at")),
        select(TerrainValidation.user_id, TerrainValidation.validated_at),
        select(Favorite.user_id, Favorite.created_at),
    ).subquery("activity")
    last_activity = func.max(activity.c.at)
    return (
        select(activity.c.user_id)
        .outerjoin(User, User.supabase_user_id == activity.c.user_id)
        .where(User.supabase_user_id.is_(None))
        .group_by(activity.c.user_id)
        .having(last_activity < cutoff)
        .order_by(last_activity.asc(), activity.c.user_id.asc())
        .limit(max_per_run)
    )


async def fetch_candidates(db: AsyncSession, cutoff: datetime, max_per_run: int) -> list[str]:
    result = await db.execute(build_candidates_query(cutoff, max_per_run))
    return [str(user_id) for user_id in result.scalars().all()]


async def purge_inactive_anonymous_accounts(
    db: AsyncSession,
    redis: Redis,
    *,
    retention_days: int,
    max_per_run: int,
    dry_run: bool,
    supabase_url: str,
    service_role_key: str,
    now: datetime | None = None,
) -> PurgeSummary:
    """Purge (ou simule en dry_run) les comptes anonymes inactifs. Idempotent."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    candidates = await fetch_candidates(db, cutoff, max_per_run)
    summary = PurgeSummary(candidates=len(candidates), dry_run=dry_run)
    quota = QuotaService(redis)

    for user_id in candidates:
        try:
            supabase_user = await get_supabase_user(user_id, supabase_url, service_role_key)
        except SupabaseAdminError:
            summary.errors += 1
            continue
        if supabase_user is not None and supabase_user.get("is_anonymous") is not True:
            summary.skipped_not_anonymous += 1
            continue
        if dry_run:
            summary.purged += 1
            continue
        try:
            await delete_user_data(user_id, db)
            await quota.delete_user_keys(user_id)
            if supabase_user is not None:
                await delete_supabase_user(user_id, supabase_url, service_role_key)
        except Exception as exc:
            await db.rollback()
            logger.warning("anonymous_purge_candidate_failed", extra={"error": type(exc).__name__})
            summary.errors += 1
            continue
        summary.purged += 1

    logger.info(
        "anonymous_purge_done",
        extra={
            "candidates": summary.candidates,
            "purged": summary.purged,
            "skipped_not_anonymous": summary.skipped_not_anonymous,
            "errors": summary.errors,
            "dry_run": summary.dry_run,
            "retention_days": retention_days,
        },
    )
    return summary
