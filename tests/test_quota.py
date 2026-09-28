"""Tests unitaires du quota journalier Redis."""

import asyncio
from hashlib import sha256
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.quota import QuotaExceededException, QuotaService


def _user_quota_key(user_id: str, date: str) -> str:
    """Construit une clé utilisateur sans UUID brut."""
    return f"quota:{sha256(user_id.encode()).hexdigest()}:{date}"


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Client Redis asynchrone isolé."""
    return AsyncMock()


@pytest.fixture
def quota_service(mock_redis: AsyncMock) -> QuotaService:
    """Service quota avec une limite d'un sommet quotidien."""
    return QuotaService(redis=mock_redis, daily_limit=1)


class TestQuotaService:
    """Tests des quotas utilisateur et installation."""

    @pytest.mark.asyncio
    async def test_user_quota_uses_exact_hashed_key(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """La clé utilisateur emploie le SHA-256 exact, jamais l'UUID brut."""
        mock_redis.eval.return_value = 1

        await quota_service.check_and_increment("user-123", "2026-04-01", "peak-abc")

        args = mock_redis.eval.call_args.args
        assert args[1:5] == (
            1,
            "quota:fcdec6df4d44dbc637c7c5b58efface52a7f8a88535423430255be0bb89bedd8:2026-04-01",
            "peak-abc",
            "1",
        )
        assert "user-123" not in args[2]

    @pytest.mark.asyncio
    async def test_same_peak_is_allowed_without_consuming_another_slot(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Le script atomique retourne zéro lorsqu'un sommet est déjà ouvert."""
        mock_redis.eval.return_value = 0

        await quota_service.check_and_increment("user-123", "2026-04-01", "peak-abc")

        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_different_peak_is_rejected_at_limit(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Le script atomique refuse un nouveau sommet au-delà de la limite."""
        mock_redis.eval.return_value = -1

        with pytest.raises(QuotaExceededException, match="Daily quota exceeded"):
            await quota_service.check_and_increment("user-123", "2026-04-01", "peak-xyz")

    @pytest.mark.asyncio
    async def test_quota_ttl_is_next_utc_midnight(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Le script reçoit exactement les 12 heures restantes jusqu'à minuit UTC."""
        mock_redis.eval.return_value = 1
        mock_now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

        with patch("app.services.quota.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.UTC = UTC
            await quota_service.check_and_increment("user-123", "2026-04-01", "peak-abc")

        assert mock_redis.eval.call_args.args[5] == "43200"

    @pytest.mark.asyncio
    async def test_quota_ttl_is_at_least_one_second_before_midnight(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """La dernière fraction de seconde avant minuit conserve le quota."""
        mock_redis.eval.return_value = 1
        mock_now = datetime(2026, 4, 1, 23, 59, 59, 500_000, tzinfo=UTC)

        with patch("app.services.quota.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.UTC = UTC
            await quota_service.check_and_increment("user-123", "2026-04-01", "peak-abc")

        assert mock_redis.eval.call_args.args[5] == "1"

    @pytest.mark.asyncio
    async def test_concurrent_different_peaks_allow_only_one(self) -> None:
        """Deux sommets concurrents ne peuvent pas tous deux passer une limite de un."""
        members: set[str] = set()
        lock = asyncio.Lock()
        redis = AsyncMock()

        async def atomic_eval(
            script: str, numkeys: int, key: str, peak_id: str, limit: str, ttl: str
        ) -> int:
            assert numkeys == 1
            assert "SCARD" in script
            assert "SADD" in script
            assert "EXPIRE" in script
            async with lock:
                if peak_id in members:
                    return 0
                if len(members) >= int(limit):
                    return -1
                members.add(peak_id)
                return 1

        redis.eval.side_effect = atomic_eval
        service = QuotaService(redis, daily_limit=1)
        results = await asyncio.gather(
            service.check_and_increment("user-123", "2026-04-01", "peak-a"),
            service.check_and_increment("user-123", "2026-04-01", "peak-b"),
            return_exceptions=True,
        )

        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, QuotaExceededException) for result in results) == 1

    @pytest.mark.asyncio
    async def test_get_remaining_checks_uses_hashed_user_key(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Le contrôle des checks restants utilise la même clé utilisateur hachée."""
        mock_redis.scard.return_value = 0

        remaining = await quota_service.get_remaining_checks("user-123", "2026-04-01")

        assert remaining == 1
        mock_redis.scard.assert_awaited_once_with(_user_quota_key("user-123", "2026-04-01"))

    @pytest.mark.asyncio
    async def test_get_remaining_checks_is_zero_at_limit(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Un quota épuisé ne laisse aucun sommet unique disponible."""
        mock_redis.scard.return_value = 1

        remaining = await quota_service.get_remaining_checks("user-123", "2026-04-01")

        assert remaining == 0

    @pytest.mark.asyncio
    async def test_installation_quota_has_separate_key(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Une installation hachée garde son espace de clés quotidien dédié."""
        installation_hash = "a" * 64
        mock_redis.eval.return_value = 1

        await quota_service.check_and_increment_installation(
            installation_hash, "2026-09-28", "peak-1"
        )

        expected_key = f"quota:installation:{installation_hash}:2026-09-28"
        assert mock_redis.eval.call_args.args[2] == expected_key

    @pytest.mark.asyncio
    async def test_installation_quota_expires_at_utc_midnight(
        self, mock_redis: AsyncMock, quota_service: QuotaService
    ) -> None:
        """Un SET installation emploie le même TTL jusqu'au prochain minuit UTC."""
        mock_redis.eval.return_value = 1
        mock_now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)

        with patch("app.services.quota.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.UTC = UTC
            await quota_service.check_and_increment_installation("a" * 64, "2026-09-28", "peak-1")

        assert mock_redis.eval.call_args.args[5] == "43200"

    @pytest.mark.asyncio
    async def test_installation_same_peak_is_allowed(self, mock_redis: AsyncMock) -> None:
        """Un sommet déjà ouvert par une installation ne consomme pas de nouvelle place."""
        mock_redis.eval.return_value = 0
        service = QuotaService(mock_redis, daily_limit=1)

        await service.check_and_increment_installation("a" * 64, "2026-09-28", "peak-1")

        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_distinct_users_have_independent_quotas(self, mock_redis: AsyncMock) -> None:
        """Une limite atteinte par un utilisateur ne bloque pas un autre sujet."""
        mock_redis.eval.side_effect = [-1, 1]
        service = QuotaService(mock_redis, daily_limit=1)

        with pytest.raises(QuotaExceededException):
            await service.check_and_increment("user-one", "2026-04-01", "peak-1")

        await service.check_and_increment("user-two", "2026-04-01", "peak-1")

        keys = [call.args[2] for call in mock_redis.eval.await_args_list]
        assert keys == [
            _user_quota_key("user-one", "2026-04-01"),
            _user_quota_key("user-two", "2026-04-01"),
        ]

    @pytest.mark.asyncio
    async def test_distinct_installations_have_independent_quotas(
        self, mock_redis: AsyncMock
    ) -> None:
        """Une installation épuisée ne bloque pas une autre installation hachée."""
        mock_redis.eval.side_effect = [-1, 1]
        service = QuotaService(mock_redis, daily_limit=1)

        with pytest.raises(QuotaExceededException):
            await service.check_and_increment_installation("a" * 64, "2026-09-28", "peak-1")

        await service.check_and_increment_installation("b" * 64, "2026-09-28", "peak-1")

        keys = [call.args[2] for call in mock_redis.eval.await_args_list]
        assert keys == [
            f"quota:installation:{'a' * 64}:2026-09-28",
            f"quota:installation:{'b' * 64}:2026-09-28",
        ]
