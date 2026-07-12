"""Tests pour les endpoints légaux /legal/privacy et /legal/cgu (story 4.4 AC1)."""

from app.main import app
from fastapi.testclient import TestClient


def test_privacy_returns_html_page() -> None:
    client = TestClient(app)
    response = client.get("/legal/privacy")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "confidentialité" in response.text.lower()


def test_cgu_returns_html_page() -> None:
    client = TestClient(app)
    response = client.get("/legal/cgu")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "conditions générales" in response.text.lower()


def test_privacy_mentions_deletion_right_and_contact() -> None:
    client = TestClient(app)
    response = client.get("/legal/privacy")

    body = response.text.lower()
    assert "delete /api/v1/user" in body
    assert "support@cloudbreak.app" in body
