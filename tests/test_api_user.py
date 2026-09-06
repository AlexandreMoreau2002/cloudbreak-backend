from datetime import UTC, datetime
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_current_user

_FAKE_USER = {"id": "user-123", "email": "t@t.com", "is_anonymous": False}


async def _override_db():
    yield AsyncMock()


@patch("app.api.v1.endpoints.user.get_user_profile", new_callable=AsyncMock, return_value=None)
def test_get_me_returns_current_user(mock_profile: AsyncMock) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "email": "alex@example.com",
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/user/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["id"] == "user-123"
    assert response.json()["is_anonymous"] is False


def test_anonymous_cannot_provision() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "anon-123",
        "is_anonymous": True,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/user/provision")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_REQUIRED"


def test_anonymous_cannot_submit_survey() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "anon-123",
        "is_anonymous": True,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.patch("/api/v1/user/survey", json={"skipped": True})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_REQUIRED"


@patch("app.api.v1.endpoints.user.get_user_profile", new_callable=AsyncMock, return_value=None)
def test_get_me_for_anonymous_session_skips_profile_lookup(mock_profile: AsyncMock) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "anon-123",
        "email": None,
        "is_anonymous": True,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/user/me")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["is_anonymous"] is True
    assert body["provisioned"] is False
    assert body["survey_completed_at"] is None
    mock_profile.assert_not_awaited()


@patch("app.api.v1.endpoints.user.provision_user", new_callable=AsyncMock)
def test_provision_creates_profile_from_current_jwt(mock_provision: AsyncMock) -> None:
    mock_provision.return_value = {
        "supabase_user_id": "user-123",
        "auth_provider": "email",
        "created_at": datetime.now(UTC),
        "converted_at": datetime.now(UTC),
    }
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "email": "a@example.com",
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/user/provision")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["supabase_user_id"] == "user-123"
    assert response.json()["auth_provider"] == "email"
    mock_provision.assert_awaited_once()


@patch("app.api.v1.endpoints.user.update_user_survey", new_callable=AsyncMock)
def test_survey_rejects_unknown_fields_and_invalid_enum(mock_update: AsyncMock) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "is_anonymous": False,
    }
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/user/survey",
                json={"acquisition_source": "not-an-option", "unexpected": "x"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    mock_update.assert_not_awaited()


@patch("app.api.v1.endpoints.user.update_user_survey", new_callable=AsyncMock)
def test_survey_persists_answer_for_permanent_account(mock_update: AsyncMock) -> None:
    mock_update.return_value = {
        "supabase_user_id": "user-123",
        "auth_provider": "email",
        "created_at": datetime.now(UTC),
        "converted_at": datetime.now(UTC),
    }
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "email": "a@example.com",
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/user/survey",
                json={"acquisition_source": "app_store", "practice": "hiker"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["supabase_user_id"] == "user-123"
    mock_update.assert_awaited_once()


def test_anonymous_cannot_update_preferences() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "anon-123",
        "is_anonymous": True,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/user/preferences", json={"newsletter_opt_in": False}
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_REQUIRED"


@patch("app.api.v1.endpoints.user.update_user_preferences", new_callable=AsyncMock)
def test_preferences_rejects_unknown_or_missing_fields(mock_update: AsyncMock) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "is_anonymous": False,
    }
    try:
        with TestClient(app) as client:
            response = client.patch("/api/v1/user/preferences", json={"unexpected": True})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    mock_update.assert_not_awaited()


@patch("app.api.v1.endpoints.user.update_user_preferences", new_callable=AsyncMock)
def test_preferences_withdraws_consent_for_permanent_account(mock_update: AsyncMock) -> None:
    mock_update.return_value = {
        "supabase_user_id": "user-123",
        "auth_provider": "email",
        "created_at": datetime.now(UTC),
        "converted_at": datetime.now(UTC),
        "newsletter_opt_in": False,
    }
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "user-123",
        "email": "a@example.com",
        "is_anonymous": False,
    }
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/v1/user/preferences", json={"newsletter_opt_in": False}
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["newsletter_opt_in"] is False
    mock_update.assert_awaited_once()


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
