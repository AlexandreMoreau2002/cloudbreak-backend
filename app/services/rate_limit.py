"""Rate-limit Redis pour les requêtes score des invités."""

from hashlib import sha256
from time import time

from redis.asyncio import Redis

ANONYMOUS_SCORE_LIMIT = 60
WINDOW_SECONDS = 60


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
        window = int(time() // WINDOW_SECONDS)
        key = f"rate_limit:anonymous_score:{ip_hash}:{window}"
        count = await self._redis.incr(key)

        if count == 1:
            await self._redis.expire(key, WINDOW_SECONDS)

        if count > ANONYMOUS_SCORE_LIMIT:
            raise RateLimitExceededException("Anonymous score rate limit exceeded")
