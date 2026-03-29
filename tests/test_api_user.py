from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app


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
