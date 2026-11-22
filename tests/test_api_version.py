from pytest import MonkeyPatch
from fastapi.testclient import TestClient

from app.core import config
from app.main import create_app


def test_returns_build_provenance_on_public_route(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "9f3c2ab")
    monkeypatch.setenv("BUILT_AT", "2026-11-22T10:15:00Z")
    monkeypatch.setenv("GIT_TAG", "v1.0.0")
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("production"))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "service": "backend",
        "sha": "9f3c2ab",
        "built_at": "2026-11-22T10:15:00Z",
        "version": config.settings.app_version,
        "tag": "v1.0.0",
    }
    assert client.get("/api/v1/version").status_code == 404


def test_returns_safe_local_fallback(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILT_AT", raising=False)
    monkeypatch.delenv("GIT_TAG", raising=False)
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("development"))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "service": "backend",
        "sha": "unknown",
        "built_at": None,
        "version": config.settings.app_version,
        "tag": None,
    }


def test_returns_null_tag_when_not_injected(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "9f3c2ab")
    monkeypatch.setenv("BUILT_AT", "2026-11-22T10:15:00Z")
    monkeypatch.setenv("GIT_TAG", "")
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("development"))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["sha"] == "9f3c2ab"
    assert response.json()["tag"] is None


def test_does_not_expose_settings_or_secrets(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_CRON_SECRET", "test-only-cron-secret")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-only-service-role")
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("development"))

    response = client.get("/version")

    assert response.status_code == 200
    assert set(response.json()) == {"service", "sha", "built_at", "version", "tag"}
    assert "test-only-cron-secret" not in response.text
    assert "test-only-service-role" not in response.text
