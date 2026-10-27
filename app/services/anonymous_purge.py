"""Purge des comptes anonymes inactifs (minimisation RGPD).

Une session Supabase anonyme laisse des données (`predictions`, `terrain_validations`,
`user_favorites`) que plus personne ne peut supprimer si la session est perdue. Ce job,
appelé par un cron, efface les identifiants sans activité depuis `retention_days` jours.

Double garde : seuls les identifiants sans ligne `users` sont candidats, et Supabase doit
confirmer `is_anonymous is True` (ou l'absence de l'utilisateur) avant toute suppression.
Aucun identifiant utilisateur n'est loggé ni renvoyé : uniquement des compteurs.

Ordre : compte Supabase d'abord, données locales ensuite. Si Supabase échoue, rien n'est
supprimé et le candidat est rejoué au prochain passage ; si le local échoue après Supabase,
le passage suivant reçoit un 404 `user_not_found` et termine la purge locale (auto-réparation).

Un verrou Redis (`lock:anon-purge`) empêche deux purges réelles simultanées ; le dry_run,
sans écriture, ne le prend pas.
"""

import logging
from uuid import uuid4
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
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

LOCK_KEY = "lock:anon-purge"
LOCK_TTL_SECONDS = 300
# Compare-et-supprime atomique : ne libère le verrou que s'il appartient toujours à ce run.
_RELEASE_LOCK_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
)


@dataclass
class PurgeSummary:
    candidates: int = 0
    purged: int = 0
    skipped_not_anonymous: int = 0
    errors: int = 0
    dry_run: bool = False
    skipped_locked: int = 0


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
    """Purge (ou simule en dry_run) les comptes anonymes inactifs. Idempotent.

    Une purge réelle prend le verrou `lock:anon-purge` ; s'il est déjà pris, renvoie un
    résumé vide avec `skipped_locked=1` (même convention que les alertes favoris).
    """
    run = _Run(db, redis, retention_days, max_per_run, dry_run, supabase_url, service_role_key)
    if dry_run:
        return await run.execute(now)

    token = uuid4().hex
    if not await redis.set(LOCK_KEY, token, nx=True, ex=LOCK_TTL_SECONDS):
        logger.info("anonymous_purge_already_running")
        return PurgeSummary(skipped_locked=1)
    try:
        return await run.execute(now)
    finally:
        try:
            await redis.eval(_RELEASE_LOCK_SCRIPT, 1, LOCK_KEY, token)  # type: ignore[misc]
        except Exception as error:
            # Ne masque ni le résultat ni l'erreur d'origine ; le TTL expirera le verrou.
            logger.error(
                "anonymous_purge_lock_release_failed", extra={"error": type(error).__name__}
            )


class _Run:
    """Un passage de purge : sélection des candidats puis traitement un par un."""

    def __init__(
        self,
        db: AsyncSession,
        redis: Redis,
        retention_days: int,
        max_per_run: int,
        dry_run: bool,
        supabase_url: str,
        service_role_key: str,
    ) -> None:
        self.db = db
        self.quota = QuotaService(redis)
        self.retention_days = retention_days
        self.max_per_run = max_per_run
        self.dry_run = dry_run
        self.supabase_url = supabase_url
        self.service_role_key = service_role_key

    async def execute(self, now: datetime | None) -> PurgeSummary:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.retention_days)
        candidates = await fetch_candidates(self.db, cutoff, self.max_per_run)
        summary = PurgeSummary(candidates=len(candidates), dry_run=self.dry_run)
        for user_id in candidates:
            await self._process(user_id, summary)
        logger.info(
            "anonymous_purge_done",
            extra={
                "candidates": summary.candidates,
                "purged": summary.purged,
                "skipped_not_anonymous": summary.skipped_not_anonymous,
                "errors": summary.errors,
                "dry_run": summary.dry_run,
                "retention_days": self.retention_days,
            },
        )
        return summary

    async def _process(self, user_id: str, summary: PurgeSummary) -> None:
        try:
            supabase_user = await get_supabase_user(
                user_id, self.supabase_url, self.service_role_key
            )
        except SupabaseAdminError:
            summary.errors += 1
            return
        if supabase_user is not None and supabase_user.get("is_anonymous") is not True:
            summary.skipped_not_anonymous += 1
            return
        if self.dry_run:
            summary.purged += 1
            return
        if supabase_user is not None:
            # Supabase d'abord : en cas d'échec rien n'est supprimé, le candidat sera rejoué.
            try:
                await delete_supabase_user(user_id, self.supabase_url, self.service_role_key)
            except Exception as exc:
                logger.warning(
                    "anonymous_purge_supabase_failed", extra={"error": type(exc).__name__}
                )
                summary.errors += 1
                return
        try:
            await delete_user_data(user_id, self.db)
        except Exception as exc:
            # Remet la session DB dans un état utilisable pour les candidats suivants. Le
            # passage suivant verra un 404 Supabase et terminera la purge locale.
            await self.db.rollback()
            logger.warning("anonymous_purge_local_failed", extra={"error": type(exc).__name__})
            summary.errors += 1
            return
        await self.quota.delete_user_keys(user_id)  # best-effort, ne lève jamais
        summary.purged += 1
