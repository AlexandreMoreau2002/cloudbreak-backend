"""
Service quota — vérification du quota journalier freemium.

Système :
  - Clé Redis historique : quota:{user_id}:{date_iso}
  - Stockage : SET de peak_ids déverrouillés (pas un compteur)
  - Limite freemium : 1 sommet unique/jour
  - Règle : toutes les heures d'un même sommet passent sans consommer de quota
  - TTL : minuit UTC (auto-reset)
  - Premium/Pro : bypass automatique (voir dependencies.py)

Format erreur :
  {"detail": "Quota journalier atteint", "code": "QUOTA_EXCEEDED"}
"""

import logging
from datetime import UTC, datetime, timedelta
from math import ceil

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

CHECK_AND_INCREMENT_SCRIPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then
    return 0
end

if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    return -1
end

redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


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
        await self._check_and_increment(self._user_quota_key(user_id, date), peak_id)

    async def check_and_increment_installation(
        self, installation_hash: str, date: str, peak_id: str
    ) -> None:
        """Vérifie le quota quotidien attaché à une installation hachée."""
        await self._check_and_increment(f"quota:installation:{installation_hash}:{date}", peak_id)

    async def _check_and_increment(self, quota_key: str, peak_id: str) -> None:
        """Déverrouille un sommet dans un SET quotidien, dans la limite configurée."""
        now_utc = datetime.now(UTC)
        tomorrow = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        ttl = max(1, ceil((tomorrow - now_utc).total_seconds()))
        result = await self._redis.eval(
            CHECK_AND_INCREMENT_SCRIPT,
            1,
            quota_key,
            peak_id,
            str(self._daily_limit),
            str(ttl),
        )  # type: ignore[misc]

        if result == -1:
            logger.warning(
                "quota_exceeded",
                extra={
                    "peak_id": peak_id,
                },
            )
            raise QuotaExceededException("Daily quota exceeded")

    @staticmethod
    def _user_quota_key(user_id: str, date: str) -> str:
        """Construit la clé quota utilisateur historique."""
        return f"quota:{user_id}:{date}"

    async def get_remaining_checks(self, user_id: str, date: str) -> int:
        """
        Retourne le nombre de sommets uniques restants.

        Args:
            user_id: ID utilisateur Supabase
            date: Date ISO 8601

        Returns:
            Nombre de sommets uniques restants (0 ou 1 pour limit=1)
        """
        quota_key = self._user_quota_key(user_id, date)
        unlocked_count = await self._redis.scard(quota_key)  # type: ignore[misc]
        return max(0, self._daily_limit - int(unlocked_count))
