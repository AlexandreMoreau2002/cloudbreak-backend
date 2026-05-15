"""
Service quota — vérification du quota journalier freemium.

Système :
  - Clé Redis : quota:{user_id}:{date_iso}
  - Stockage : SET de peak_ids déverrouillés (pas un compteur)
  - Limite freemium : 1 sommet unique/jour
  - Règle : toutes les heures d'un même sommet passent sans consommer de quota
  - TTL : minuit UTC (auto-reset)
  - Premium/Pro : bypass automatique (voir dependencies.py)

Format erreur :
  {"detail": "Quota journalier atteint", "code": "QUOTA_EXCEEDED"}
"""

import logging
from redis.asyncio import Redis
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)


class QuotaExceededException(Exception):
    """Levée quand le quota journalier freemium est dépassé."""

    pass


class QuotaService:
    """Gère le quota journalier des utilisateurs freemium."""

    def __init__(self, redis: Redis, daily_limit: int = 1):
        """
        Initialise le service quota.

        Args:
            redis: Client Redis pour le stockage du SET de sommets déverrouillés
            daily_limit: Nombre de sommets uniques autorisés par jour (défaut: 1)
        """
        self._redis = redis
        self._daily_limit = daily_limit

    async def check_and_increment(self, user_id: str, date: str, peak_id: str) -> None:
        """
        Vérifie le quota et déverrouille le sommet si nécessaire.

        Si le sommet est déjà déverrouillé aujourd'hui → toutes ses heures passent.
        Si le quota de sommets uniques est atteint → lève QuotaExceededException.
        Sinon → déverrouille le sommet et set le TTL.

        Args:
            user_id: ID utilisateur Supabase
            date: Date ISO 8601 (ex: "2026-04-01")
            peak_id: ID du sommet consulté

        Raises:
            QuotaExceededException: Si quota de sommets uniques dépassé
        """
        quota_key = f"quota:{user_id}:{date}"

        # Si ce sommet est déjà déverrouillé aujourd'hui → allow
        already_unlocked = await self._redis.sismember(quota_key, peak_id)  # type: ignore[misc]
        if already_unlocked:
            return

        # Vérifier si le quota de sommets uniques est atteint
        unlocked_count = await self._redis.scard(quota_key)  # type: ignore[misc]
        if unlocked_count >= self._daily_limit:
            logger.warning(
                "quota_exceeded",
                extra={
                    "user_id": user_id,
                    "date": date,
                    "peak_id": peak_id,
                    "unlocked_count": int(unlocked_count),
                },
            )
            raise QuotaExceededException(f"Daily quota exceeded for {user_id} on {date}")

        # Déverrouiller ce sommet pour aujourd'hui (opération atomique)
        now_utc = datetime.now(UTC)
        tomorrow = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        ttl = int((tomorrow - now_utc).total_seconds())
        async with self._redis.pipeline() as pipe:
            await pipe.sadd(quota_key, peak_id)  # type: ignore[misc]
            await pipe.expire(quota_key, ttl)
            await pipe.execute()

        logger.info(
            "quota_peak_unlocked",
            extra={
                "user_id": user_id,
                "date": date,
                "peak_id": peak_id,
                "unlocked_count": int(unlocked_count) + 1,
            },
        )

    async def get_remaining_checks(self, user_id: str, date: str) -> int:
        """
        Retourne le nombre de sommets uniques restants.

        Args:
            user_id: ID utilisateur Supabase
            date: Date ISO 8601

        Returns:
            Nombre de sommets uniques restants (0 ou 1 pour limit=1)
        """
        quota_key = f"quota:{user_id}:{date}"
        unlocked_count = await self._redis.scard(quota_key)  # type: ignore[misc]
        return max(0, self._daily_limit - int(unlocked_count))
