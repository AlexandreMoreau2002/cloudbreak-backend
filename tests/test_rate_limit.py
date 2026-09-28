"""Tests unitaires du rate-limit Redis des requêtes score invitées."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.rate_limit import RateLimitExceededException, RateLimitService


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Client Redis asynchrone isolé."""
    return AsyncMock()


class TestRateLimitService:
    """Tests de la fenêtre fixe par IP pour le score invité."""

    @pytest.mark.asyncio
    async def test_first_request_uses_exact_digest_in_frozen_window(
        self, mock_redis: AsyncMock
    ) -> None:
        """La clé est le digest SHA-256 exact dans la fenêtre fixe attendue."""
        mock_redis.eval.return_value = 1

        with patch("app.services.rate_limit.time.time", return_value=120.0):
            await RateLimitService(mock_redis).check_anonymous_score("198.51.100.8")

        args = mock_redis.eval.call_args.args
        assert args[1:] == (
            1,
            "rate_limit:anonymous_score:c53bee22afaf61cffd4076a3632d42f24701139f4219567bec9533e3cdd628cc:2",
            "60",
        )
        assert "198.51.100.8" not in args[2]

    @pytest.mark.asyncio
    async def test_requests_through_sixty_are_allowed(self, mock_redis: AsyncMock) -> None:
        """Les compteurs 1 à 60 restent sous la limite."""
        mock_redis.eval.side_effect = range(1, 61)
        service = RateLimitService(mock_redis)

        with patch("app.services.rate_limit.time.time", return_value=120.0):
            for _ in range(60):
                await service.check_anonymous_score("198.51.100.8")

        assert mock_redis.eval.await_count == 60

    @pytest.mark.asyncio
    async def test_sixty_first_request_is_rejected(self, mock_redis: AsyncMock) -> None:
        """Le 61e appel de la fenêtre est refusé."""
        mock_redis.eval.return_value = 61

        with patch("app.services.rate_limit.time.time", return_value=120.0):
            with pytest.raises(RateLimitExceededException):
                await RateLimitService(mock_redis).check_anonymous_score("198.51.100.8")

    @pytest.mark.asyncio
    async def test_orphan_counter_gets_ttl_inside_atomic_script(
        self, mock_redis: AsyncMock
    ) -> None:
        """Une clé existante sans TTL est réparée dans le même script atomique."""
        mock_redis.eval.return_value = 2

        with patch("app.services.rate_limit.time.time", return_value=120.0):
            await RateLimitService(mock_redis).check_anonymous_score("198.51.100.8")

        script = mock_redis.eval.call_args.args[0]
        assert "redis.call('TTL', KEYS[1]) == -1" in script
        assert "redis.call('EXPIRE', KEYS[1], ARGV[1])" in script
