"""Rate-limit Redis pour les requêtes score des invités."""

import time
from hashlib import sha256

from redis.asyncio import Redis

ANONYMOUS_SCORE_LIMIT = 60
WINDOW_SECONDS = 60

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
