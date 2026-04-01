"""
Tests unitaires du service quota — vérification du quota journalier freemium.

Cas testés:
  1. Nouveau user → 1 check restant
  2. Après 1 appel → 0 restants
  3. 1er check incrémente Redis + setter TTL minuit UTC
  4. 2e check au-delà de la limite → QuotaExceededException
  5. TTL expire à minuit UTC (secondes jusqu'à minuit)
  6. Format clé Redis correct (quota:user_id:date_iso)
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.services.quota import QuotaService, QuotaExceededException


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    return AsyncMock()


@pytest.fixture
def quota_service(mock_redis: AsyncMock) -> QuotaService:
    """Service quota avec Redis mocké."""
    return QuotaService(redis=mock_redis, daily_limit=1)


class TestQuotaService:
    """Tests du service quota."""

    @pytest.mark.asyncio
    async def test_quota_get_remaining_checks_freemium_new_user(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Nouveau user freemium → 1 check restant."""
        mock_redis.get.return_value = None

        remaining = await quota_service.get_remaining_checks(user_id="user-123", date="2026-04-01")

        assert remaining == 1
        mock_redis.get.assert_called_once_with("quota:user-123:2026-04-01")

    @pytest.mark.asyncio
    async def test_quota_get_remaining_checks_after_one_call(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Après 1 check → 0 restants."""
        mock_redis.get.return_value = b"1"  # Redis retourne bytes

        remaining = await quota_service.get_remaining_checks(user_id="user-123", date="2026-04-01")

        assert remaining == 0

    @pytest.mark.asyncio
    async def test_quota_increment_first_check(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """1er check : INCR Redis + setter TTL minuit UTC."""
        mock_redis.get.return_value = None
        mock_redis.incr.return_value = 1

        # Mock datetime à 12:00 UTC
        mock_now = datetime(2026, 4, 1, 12, 0, 0)

        with patch("app.services.quota.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = mock_now

            await quota_service.check_and_increment(user_id="user-123", date="2026-04-01")

        # INCR appelé
        mock_redis.incr.assert_called_once_with("quota:user-123:2026-04-01")

        # expire() appelé avec TTL = 12 heures (43200 secondes)
        mock_redis.expire.assert_called_once()
        call_args = mock_redis.expire.call_args
        assert call_args[0][0] == "quota:user-123:2026-04-01"
        assert 43100 < call_args[0][1] < 43300  # ~12h en secondes

    @pytest.mark.asyncio
    async def test_quota_exceeds_daily_limit(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """2e check au-delà du limit → QuotaExceededException."""
        # Redis retourne "1" (déjà 1 check)
        mock_redis.get.return_value = b"1"

        with pytest.raises(QuotaExceededException) as exc_info:
            await quota_service.check_and_increment(user_id="user-123", date="2026-04-01")

        assert "Daily quota exceeded" in str(exc_info.value)
        # INCR ne doit PAS être appelé
        mock_redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_quota_redis_key_format_correct(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Format clé Redis = quota:{user_id}:{date}."""
        mock_redis.get.return_value = None
        mock_redis.incr.return_value = 1

        await quota_service.check_and_increment(user_id="user-abc", date="2026-12-25")

        # Vérifier la clé utilisée
        assert mock_redis.get.call_args[0][0] == "quota:user-abc:2026-12-25"
        assert mock_redis.incr.call_args[0][0] == "quota:user-abc:2026-12-25"

    @pytest.mark.asyncio
    async def test_quota_ttl_seconds_until_midnight_utc(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """TTL correct = secondes jusqu'à minuit UTC."""
        mock_redis.get.return_value = None
        mock_redis.incr.return_value = 1

        # Test à 13:30 UTC (10h 30min jusqu'à minuit)
        mock_now = datetime(2026, 4, 1, 13, 30, 0)

        with patch("app.services.quota.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = mock_now

            await quota_service.check_and_increment(user_id="user-123", date="2026-04-01")

        # TTL = 10*3600 + 30*60 = 37800 secondes
        call_args = mock_redis.expire.call_args
        assert call_args[0][1] == 37800

    @pytest.mark.asyncio
    async def test_quota_reset_at_midnight_utc(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Jour suivant → nouveau compteur (Redis expire auto + clé différente)."""
        mock_redis.get.return_value = b"1"

        # 2026-04-01 → quota:user-123:2026-04-01 = 1
        # Ne peut pas faire 2e check
        with pytest.raises(QuotaExceededException):
            await quota_service.check_and_increment(user_id="user-123", date="2026-04-01")

        # Reset Redis mock
        mock_redis.reset_mock()
        mock_redis.get.return_value = None  # Nouvelle date = pas de quota
        mock_redis.incr.return_value = 1

        # 2026-04-02 → quota:user-123:2026-04-02 = None (nouveau jour)
        await quota_service.check_and_increment(user_id="user-123", date="2026-04-02")

        # INCR appelé sur la nouvelle clé
        assert mock_redis.incr.call_args[0][0] == "quota:user-123:2026-04-02"

    @pytest.mark.asyncio
    async def test_quota_multiple_users_independent(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Quotas indépendants par user."""

        # User 1 a déjà 1 check
        # User 2 n'en a pas
        def get_side_effect(key: str) -> bytes | None:
            if key == "quota:user-1:2026-04-01":
                return b"1"
            return None

        mock_redis.get.side_effect = get_side_effect
        mock_redis.incr.return_value = 1

        # User 1 → quota exceeded
        with pytest.raises(QuotaExceededException):
            await quota_service.check_and_increment(user_id="user-1", date="2026-04-01")

        # User 2 → OK
        await quota_service.check_and_increment(user_id="user-2", date="2026-04-01")

        # INCR appelé pour user 2 seulement
        mock_redis.incr.assert_called_once_with("quota:user-2:2026-04-01")
