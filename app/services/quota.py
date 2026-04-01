"""
Service quota — vérification du quota journalier freemium.

Système :
  - Clé Redis : quota:{user_id}:{date_iso}
  - Limite freemium : 1 check/jour
  - TTL : minuit UTC (auto-reset)
  - Premium/Pro : bypass automatique (voir dependencies.py)

Format erreur :
  {"detail": "Quota journalier atteint", "code": "QUOTA_EXCEEDED"}
"""

import logging
from datetime import datetime, timedelta
from redis.asyncio import Redis

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
            redis: Client Redis pour le stockage du compteur
            daily_limit: Nombre de checks autorisés par jour (défaut: 1)
        """
        self._redis = redis
        self._daily_limit = daily_limit

    async def check_and_increment(self, user_id: str, date: str) -> None:
        """
        Vérifie le quota et l'incrémente.

        Lève QuotaExceededException si le quota est dépassé.

        Args:
            user_id: ID utilisateur Supabase
            date: Date ISO 8601 (ex: "2026-04-01")

        Raises:
            QuotaExceededException: Si quota dépassé
        """
        quota_key = f"quota:{user_id}:{date}"

        # Vérifier le compteur actuel
        checks = await self._redis.get(quota_key)
        checks_int = int(checks) if checks else 0

        if checks_int >= self._daily_limit:
            logger.warning(
                "quota_exceeded",
                extra={
                    "user_id": user_id,
                    "date": date,
                    "checks": checks_int,
                },
            )
            raise QuotaExceededException(f"Daily quota exceeded for {user_id} on {date}")

        # Incrémenter et définir TTL minuit UTC
        await self._redis.incr(quota_key)

        tomorrow = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        ttl = int((tomorrow - datetime.utcnow()).total_seconds())
        await self._redis.expire(quota_key, ttl)

        logger.info(
            "quota_incremented",
            extra={
                "user_id": user_id,
                "date": date,
                "checks_now": checks_int + 1,
            },
        )

    async def get_remaining_checks(self, user_id: str, date: str) -> int:
        """
        Retourne le nombre de checks restants.

        Args:
            user_id: ID utilisateur Supabase
            date: Date ISO 8601

        Returns:
            Nombre de checks restants (0 ou 1 pour limit=1)
        """
        quota_key = f"quota:{user_id}:{date}"
        checks = await self._redis.get(quota_key)
        checks_int = int(checks) if checks else 0
        return self._daily_limit - checks_int
