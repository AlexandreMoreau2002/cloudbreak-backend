"""Tests unitaires du rate-limit Redis des requêtes score invitées."""

from unittest.mock import AsyncMock

import pytest

from app.services.rate_limit import RateLimitExceededException, RateLimitService


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Client Redis asynchrone isolé."""
    return AsyncMock()


class TestRateLimitService:
    """Tests de la fenêtre fixe par IP pour le score invité."""

    @pytest.mark.asyncio
    async def test_first_request_sets_window_ttl(self, mock_redis: AsyncMock) -> None:
        """Le premier INCR initialise l'expiration de la fenêtre à 60 secondes."""
        mock_redis.incr.return_value = 1

        await RateLimitService(mock_redis).check_anonymous_score("198.51.100.8")

        key = mock_redis.incr.call_args.args[0]
        assert key.startswith("rate_limit:anonymous_score:")
        assert "198.51.100.8" not in key
        mock_redis.expire.assert_awaited_once_with(key, 60)

    @pytest.mark.asyncio
    async def test_requests_through_sixty_are_allowed(self, mock_redis: AsyncMock) -> None:
        """Les compteurs 1 à 60 restent sous la limite."""
        mock_redis.incr.side_effect = range(1, 61)
        service = RateLimitService(mock_redis)

        for _ in range(60):
            await service.check_anonymous_score("198.51.100.8")

        assert mock_redis.incr.await_count == 60
        assert mock_redis.expire.await_count == 1

    @pytest.mark.asyncio
    async def test_sixty_first_request_is_rejected(self, mock_redis: AsyncMock) -> None:
        """Le 61e appel de la fenêtre est refusé."""
        mock_redis.incr.return_value = 61

        with pytest.raises(RateLimitExceededException):
            await RateLimitService(mock_redis).check_anonymous_score("198.51.100.8")

        key = mock_redis.incr.call_args.args[0]
        assert "198.51.100.8" not in key
        mock_redis.expire.assert_not_awaited()
