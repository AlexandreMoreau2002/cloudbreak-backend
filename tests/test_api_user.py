from app.main import app
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.core.dependencies import get_current_user

_FAKE_USER = {"id": "user-123", "email": "t@t.com"}


def test_get_me_returns_current_user() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "email": "alex@example.com",
    }

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/user/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"id": "user-123", "email": "alex@example.com"}


@patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.user.delete_user_data", new_callable=AsyncMock)
def test_delete_user_retourne_204(
    mock_delete_data: AsyncMock, mock_delete_supabase: AsyncMock
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            response = client.delete("/api/v1/user/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""


def test_delete_user_sans_auth_retourne_403() -> None:
    with TestClient(app) as client:
        response = client.delete("/api/v1/user/")

    assert response.status_code == 403
    assert response.json() == {"detail": "Not authenticated"}


@patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.user.delete_user_data", new_callable=AsyncMock)
def test_delete_user_supabase_erreur_retourne_500(
    mock_delete_data: AsyncMock, mock_delete_supabase: AsyncMock
) -> None:
    from fastapi import HTTPException

    mock_delete_supabase.side_effect = HTTPException(
        status_code=500,
        detail={"detail": "Erreur suppression compte", "code": "INTERNAL_ERROR"},
    )
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            response = client.delete("/api/v1/user/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500


@patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.user.delete_user_data", new_callable=AsyncMock)
def test_delete_user_supprime_donnees_db(
    mock_delete_data: AsyncMock, mock_delete_supabase: AsyncMock
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            client.delete("/api/v1/user/")
    finally:
        app.dependency_overrides.clear()

    mock_delete_data.assert_called_once()
    call_args = mock_delete_data.call_args
    assert call_args[0][0] == "user-123"


@patch("app.api.v1.endpoints.user.track")
@patch("app.api.v1.endpoints.user.delete_supabase_user", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.user.delete_user_data", new_callable=AsyncMock)
def test_delete_user_appelle_track_account_deleted(
    mock_delete_data: AsyncMock, mock_delete_supabase: AsyncMock, mock_track: object
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            client.delete("/api/v1/user/")
    finally:
        app.dependency_overrides.clear()

    mock_track.assert_called_once_with("account_deleted", "user-123")  # type: ignore[attr-defined]
