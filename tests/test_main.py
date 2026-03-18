from app.main import app
from fastapi.testclient import TestClient


def test_lifespan_startup() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
