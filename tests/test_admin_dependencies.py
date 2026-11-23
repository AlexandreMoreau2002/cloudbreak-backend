from unittest.mock import patch

import pytest

from app.core.dependencies import require_admin
from app.core.errors import ApiError


def test_admin_without_credentials_is_forbidden() -> None:
    with pytest.raises(ApiError) as error:
        require_admin(None)
    assert error.value.code == "ADMIN_FORBIDDEN"


def test_admin_allowlist_is_required() -> None:
    credentials = type("Credentials", (), {"credentials": "token"})()
    with (
        patch(
            "app.core.dependencies.decode_supabase_jwt",
            return_value={"sub": "u", "app_metadata": {"role": "admin"}},
        ),
        patch("app.core.dependencies.settings.admin_user_ids", ""),
    ):
        with pytest.raises(ApiError):
            require_admin(credentials)
