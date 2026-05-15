"""
Tests unitaires du service quota — vérification du quota journalier freemium.

Cas testés:
  1. Nouveau peak → déverrouillé (sadd + expire appelés, pas d'exception)
  2. Même peak → allow sans sadd (sismember True → retour direct)
  3. Quota atteint (peak différent) → QuotaExceededException, sadd non appelé
  4. TTL correct (~12h quand appelé à 12:00 UTC)
  5. Format clé Redis correct (quota:user_id:date_iso)
  6. Quotas indépendants par user
  7. get_remaining_checks : sommet non déverrouillé → 1 restant
  8. get_remaining_checks : quota épuisé → 0 restants
"""

import pytest
from datetime import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from app.services.quota import QuotaExceededException, QuotaService


def _make_mock_redis() -> AsyncMock:
    """
    Crée un mock Redis avec pipeline() correctement configuré.

    pipeline() doit retourner un async context manager (AsyncMock ne le fait
    pas automatiquement). On utilise asynccontextmanager pour simuler le pipe.
    """
    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()

    @asynccontextmanager
    async def mock_pipeline() -> object:
        yield mock_pipe

    mock_redis.pipeline = mock_pipeline
    # Expose le pipe pour les assertions dans les tests
    mock_redis._pipe = mock_pipe
    return mock_redis


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    return _make_mock_redis()


@pytest.fixture
def quota_service(mock_redis: AsyncMock) -> QuotaService:
    """Service quota avec Redis mocké."""
    return QuotaService(redis=mock_redis, daily_limit=1)


class TestQuotaService:
    """Tests du service quota."""

    @pytest.mark.asyncio
    async def test_quota_new_peak_unlocked(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Nouveau peak → sadd et expire appelés via pipeline, pas d'exception."""
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 0

        await quota_service.check_and_increment(
            user_id="user-123", date="2026-04-01", peak_id="peak-abc"
        )

        mock_redis._pipe.sadd.assert_called_once_with("quota:user-123:2026-04-01", "peak-abc")
        mock_redis._pipe.expire.assert_called_once()
        mock_redis._pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_quota_same_peak_allow_without_sadd(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Même peak déjà déverrouillé → retour direct, pipeline NON appelé."""
        mock_redis.sismember.return_value = True

        await quota_service.check_and_increment(
            user_id="user-123", date="2026-04-01", peak_id="peak-abc"
        )

        mock_redis._pipe.sadd.assert_not_called()
        mock_redis.scard.assert_not_called()

    @pytest.mark.asyncio
    async def test_quota_exceeded_different_peak(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Quota atteint avec peak différent → QuotaExceededException, pipeline NON appelé."""
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 1  # daily_limit atteint

        with pytest.raises(QuotaExceededException) as exc_info:
            await quota_service.check_and_increment(
                user_id="user-123", date="2026-04-01", peak_id="peak-xyz"
            )

        assert "Daily quota exceeded" in str(exc_info.value)
        mock_redis._pipe.sadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_quota_ttl_approximately_twelve_hours(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """TTL correct : ~12h quand appelé à 12:00 UTC."""
        from datetime import UTC

        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 0

        mock_now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

        with patch("app.services.quota.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.UTC = UTC

            await quota_service.check_and_increment(
                user_id="user-123", date="2026-04-01", peak_id="peak-abc"
            )

        call_args = mock_redis._pipe.expire.call_args
        assert call_args[0][0] == "quota:user-123:2026-04-01"
        assert 43100 < call_args[0][1] < 43300  # ~12h en secondes

    @pytest.mark.asyncio
    async def test_quota_redis_key_format_correct(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Format clé Redis = quota:{user_id}:{date}."""
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 0

        await quota_service.check_and_increment(
            user_id="user-abc", date="2026-12-25", peak_id="peak-001"
        )

        mock_redis.sismember.assert_called_once_with("quota:user-abc:2026-12-25", "peak-001")
        mock_redis._pipe.sadd.assert_called_once_with("quota:user-abc:2026-12-25", "peak-001")

    @pytest.mark.asyncio
    async def test_quota_multiple_users_independent(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Quotas indépendants par user."""

        def sismember_side_effect(key: str, member: str) -> bool:
            return False

        def scard_side_effect(key: str) -> int:
            if key == "quota:user-1:2026-04-01":
                return 1  # quota atteint pour user-1
            return 0

        mock_redis.sismember.side_effect = sismember_side_effect
        mock_redis.scard.side_effect = scard_side_effect

        # User 1 → quota exceeded
        with pytest.raises(QuotaExceededException):
            await quota_service.check_and_increment(
                user_id="user-1", date="2026-04-01", peak_id="peak-abc"
            )

        # User 2 → OK
        await quota_service.check_and_increment(
            user_id="user-2", date="2026-04-01", peak_id="peak-abc"
        )

        # sadd appelé pour user-2 seulement (via pipeline)
        mock_redis._pipe.sadd.assert_called_once_with("quota:user-2:2026-04-01", "peak-abc")

    @pytest.mark.asyncio
    async def test_quota_get_remaining_checks_new_user(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Sommet non déverrouillé → scard=0 → 1 restant."""
        mock_redis.scard.return_value = 0

        remaining = await quota_service.get_remaining_checks(user_id="user-123", date="2026-04-01")

        assert remaining == 1
        mock_redis.scard.assert_called_once_with("quota:user-123:2026-04-01")

    @pytest.mark.asyncio
    async def test_quota_get_remaining_checks_quota_exhausted(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Quota épuisé → scard=1 → 0 restants."""
        mock_redis.scard.return_value = 1

        remaining = await quota_service.get_remaining_checks(user_id="user-123", date="2026-04-01")

        assert remaining == 0
