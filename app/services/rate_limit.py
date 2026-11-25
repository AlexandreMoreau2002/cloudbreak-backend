"""Rate-limit Redis pour les requêtes score des invités."""

import time
from hashlib import sha256

from redis.asyncio import Redis

from app.core.config import settings

ANONYMOUS_SCORE_LIMIT = 60
SCORE_WEEK_LIMIT = 12
PUSH_TOKEN_LIMIT = 10
PUSH_TOKEN_DEV_LIMIT = 1000
DELETE_ACCOUNT_LIMIT = 5
WINDOW_SECONDS = 60
DELETE_ACCOUNT_WINDOW_SECONDS = 3600

INCREMENT_WITH_TTL_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) == -1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimitExceededException(Exception):
    """Levée quand une requête dépasse la limite de sa fenêtre."""

    pass


class RateLimitService:
    """Gère les compteurs Redis à fenêtre fixe."""

    def __init__(self, redis: Redis) -> None:
        """Initialise le service avec son client Redis."""
        self._redis = redis

    async def check_anonymous_score(self, client_ip: str) -> None:
        """Autorise au plus 60 requêtes score invitées par IP et par minute."""
        ip_hash = sha256(client_ip.encode()).hexdigest()
        window = int(time.time() // WINDOW_SECONDS)
        key = f"rate_limit:anonymous_score:{ip_hash}:{window}"
        count = await self._redis.eval(INCREMENT_WITH_TTL_SCRIPT, 1, key, str(WINDOW_SECONDS))  # type: ignore[misc]

        if count > ANONYMOUS_SCORE_LIMIT:
            raise RateLimitExceededException("Anonymous score rate limit exceeded")

    async def check_score_week(self, user_id: str) -> None:
        """Autorise au plus 12 lectures hebdomadaires par utilisateur et par minute."""
        user_hash = sha256(user_id.encode()).hexdigest()
        window = int(time.time() // WINDOW_SECONDS)
        key = f"rate_limit:score_week:{user_hash}:{window}"
        count = await self._redis.eval(INCREMENT_WITH_TTL_SCRIPT, 1, key, str(WINDOW_SECONDS))  # type: ignore[misc]

        if count > SCORE_WEEK_LIMIT:
            raise RateLimitExceededException("Score week rate limit exceeded")

    async def check_push_token(self, user_id: str) -> None:
        """Autorise 10 enregistrements de token push par utilisateur et par minute (1000 en dev)."""
        user_hash = sha256(user_id.encode()).hexdigest()
        window = int(time.time() // WINDOW_SECONDS)
        key = f"rate_limit:push_token:{user_hash}:{window}"
        count = await self._redis.eval(INCREMENT_WITH_TTL_SCRIPT, 1, key, str(WINDOW_SECONDS))  # type: ignore[misc]

        # Hors production (rechargements Metro répétés), la limite est relevée.
        is_production = settings.environment.lower() == "production"
        limit = PUSH_TOKEN_LIMIT if is_production else PUSH_TOKEN_DEV_LIMIT
        if count > limit:
            raise RateLimitExceededException("Push token rate limit exceeded")

    async def check_delete_account(self, user_id: str) -> None:
        """Autorise au plus 5 tentatives de suppression de compte par utilisateur et par heure."""
        user_hash = sha256(user_id.encode()).hexdigest()
        window = int(time.time() // DELETE_ACCOUNT_WINDOW_SECONDS)
        key = f"rate_limit:delete_account:{user_hash}:{window}"
        count = await self._redis.eval(  # type: ignore[misc]
            INCREMENT_WITH_TTL_SCRIPT, 1, key, str(DELETE_ACCOUNT_WINDOW_SECONDS)
        )

        if count > DELETE_ACCOUNT_LIMIT:
            raise RateLimitExceededException("Delete account rate limit exceeded")
