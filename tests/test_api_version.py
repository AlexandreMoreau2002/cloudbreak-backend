from pytest import MonkeyPatch, mark
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


@mark.parametrize(
    ("tag", "expected"),
    [
        ("", None),
        ("nightly", None),
        ("v1.2.3-rc.1", None),
        ("v12.34.56", "v12.34.56"),
    ],
)
def test_only_returns_release_tags(
    monkeypatch: MonkeyPatch, tag: str, expected: str | None
) -> None:
    sha = "9f3c2ab9f3c2ab9f3c2ab9f3c2ab9f3c2ab9f3c2"
    monkeypatch.setenv("GIT_SHA", sha)
    monkeypatch.setenv("BUILT_AT", "2026-11-22T10:15:00Z")
    monkeypatch.setenv("GIT_TAG", tag)
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("development"))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["sha"] == sha
    assert response.json()["built_at"] == "2026-11-22T10:15:00Z"
    assert response.json()["tag"] == expected


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


@mark.parametrize("sha", [None, "", "   ", "unknown", "not-a-sha"])
def test_ignores_build_timestamp_and_tag_without_valid_sha(
    monkeypatch: MonkeyPatch, sha: str | None
) -> None:
    if sha is None:
        monkeypatch.delenv("GIT_SHA", raising=False)
    else:
        monkeypatch.setenv("GIT_SHA", sha)
    monkeypatch.setenv("BUILT_AT", "2026-11-22T10:15:00Z")
    monkeypatch.setenv("GIT_TAG", "v1.0.0")
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("development"))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["sha"] == "unknown"
    assert response.json()["built_at"] is None
    assert response.json()["tag"] is None


@mark.parametrize(
    ("built_at", "expected"),
    [
        ("2026-11-22T11:15:00+01:00", "2026-11-22T10:15:00Z"),
        ("2026-11-22T23:15:00-05:00", "2026-11-23T04:15:00Z"),
        ("2026-11-22T10:15:00", None),
        ("invalid", None),
        (None, None),
    ],
)
def test_returns_utc_build_timestamp(
    monkeypatch: MonkeyPatch, built_at: str | None, expected: str | None
) -> None:
    monkeypatch.setenv("GIT_SHA", "9f3c2ab")
    if built_at is None:
        monkeypatch.delenv("BUILT_AT", raising=False)
    else:
        monkeypatch.setenv("BUILT_AT", built_at)
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None))
    client = TestClient(create_app("development"))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["built_at"] == expected
