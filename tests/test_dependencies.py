from app.main import app
from unittest.mock import patch
from fastapi.testclient import TestClient

client = TestClient(app)


def test_get_me_without_token() -> None:
    response = client.get("/api/v1/user/me")
    assert response.status_code == 403


def test_get_me_invalid_token() -> None:
    response = client.get(
        "/api/v1/user/me",
        headers={"Authorization": "Bearer token.invalide.ici"},
    )
    assert response.status_code == 401


def test_get_me_valid_token() -> None:
    payload = {"sub": "user-123", "email": "test@cloudbreak.app"}
    with patch("app.core.dependencies.decode_supabase_jwt", return_value=payload):
        response = client.get(
            "/api/v1/user/me",
            headers={"Authorization": "Bearer valid.token.here"},
        )
    assert response.status_code == 200
    assert response.json()["id"] == "user-123"
    assert response.json()["email"] == "test@cloudbreak.app"


def test_get_me_token_without_sub() -> None:
    payload = {"email": "test@cloudbreak.app"}
    with patch("app.core.dependencies.decode_supabase_jwt", return_value=payload):
        response = client.get(
            "/api/v1/user/me",
            headers={"Authorization": "Bearer valid.token.here"},
        )
    assert response.status_code == 401
