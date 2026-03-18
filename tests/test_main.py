from fastapi.testclient import TestClient
from app.main import app


def test_lifespan_startup() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
