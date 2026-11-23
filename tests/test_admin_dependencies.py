from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.dependencies import require_admin
from app.core.errors import ApiError


@pytest.mark.asyncio
async def test_admin_without_credentials_is_forbidden() -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    with pytest.raises(ApiError) as error:
        await require_admin(None, db)
    assert error.value.code == "ADMIN_FORBIDDEN"


@pytest.mark.asyncio
async def test_admin_allowlist_is_required() -> None:
    credentials = type("Credentials", (), {"credentials": "token"})()
    db = MagicMock()
    db.commit = AsyncMock()
    with (
        patch(
            "app.core.dependencies.decode_supabase_jwt",
            return_value={"sub": "u", "app_metadata": {"role": "admin"}},
        ),
        patch("app.core.dependencies.settings.admin_user_ids", ""),
    ):
        with pytest.raises(ApiError):
            await require_admin(credentials, db)


@pytest.mark.asyncio
async def test_admin_in_allowlist_with_admin_role_is_allowed() -> None:
    credentials = type("Credentials", (), {"credentials": "token"})()
    db = MagicMock()
    db.commit = AsyncMock()
    with (
        patch(
            "app.core.dependencies.decode_supabase_jwt",
            return_value={"sub": "allowed", "app_metadata": {"role": "admin"}},
        ),
        patch("app.core.dependencies.settings.admin_user_ids", "allowed,another"),
    ):
        assert await require_admin(credentials, db) == {"id": "allowed"}


@pytest.mark.asyncio
async def test_admin_outside_allowlist_or_missing_role_is_forbidden() -> None:
    credentials = type("Credentials", (), {"credentials": "token"})()
    db = MagicMock()
    db.commit = AsyncMock()
    with patch("app.core.dependencies.settings.admin_user_ids", "allowed"):
        with patch(
            "app.core.dependencies.decode_supabase_jwt",
            return_value={"sub": "other", "app_metadata": {"role": "admin"}},
        ):
            with pytest.raises(ApiError):
                await require_admin(credentials, db)
        with patch("app.core.dependencies.decode_supabase_jwt", return_value={"sub": "allowed"}):
            with pytest.raises(ApiError):
                await require_admin(credentials, db)
