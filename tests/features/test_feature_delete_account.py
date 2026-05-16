"""Feature test — flux HTTP complet DELETE /api/v1/user/ (suppression de compte RGPD)."""

from app.main import app
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.core.dependencies import get_current_user

_FAKE_USER = {"id": "user-456", "email": "feature@test.com"}


def test_delete_account_sans_auth_retourne_403() -> None:
    """Sans header Authorization, FastAPI HTTPBearer retourne 403."""
    with TestClient(app) as client:
        response = client.delete("/api/v1/user/")

    assert response.status_code == 403


@patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.user.delete_user_data", new_callable=AsyncMock)
def test_delete_account_flux_complet_retourne_204(
    mock_delete_data: AsyncMock, mock_delete_supabase: AsyncMock
) -> None:
    """Flux nominal : auth valide → suppression DB → suppression Supabase → 204."""
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            response = client.delete("/api/v1/user/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""
    mock_delete_data.assert_called_once()
    mock_delete_supabase.assert_called_once()


@patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.user.delete_user_data", new_callable=AsyncMock)
def test_delete_account_ordre_suppression(
    mock_delete_data: AsyncMock, mock_delete_supabase: AsyncMock
) -> None:
    """Vérifie que la suppression DB intervient avant Supabase."""
    call_order: list[str] = []
    mock_delete_data.side_effect = lambda *a, **kw: call_order.append("db") or None
    mock_delete_supabase.side_effect = lambda *a, **kw: call_order.append("supabase") or None

    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            client.delete("/api/v1/user/")
    finally:
        app.dependency_overrides.clear()

    assert call_order == ["db", "supabase"]
