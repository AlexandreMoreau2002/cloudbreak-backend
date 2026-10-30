from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_reads_explicit_values() -> None:
    settings = Settings(
        database_url="postgresql://example",
        redis_url="redis://example",
        environment="test",
    )

    assert settings.database_url == "postgresql://example"
    assert settings.redis_url == "redis://example"
    assert settings.environment == "test"


def test_settings_defaults_are_defined() -> None:
    settings = Settings()

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.redis_url.startswith("redis://")


def test_development_sandbox_requires_no_private_apple_api_credentials() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        apple_bundle_id="com.alexandremoreau.cloudbreak",
        apple_environment="Sandbox",
    )

    assert settings.apple_app_id is None
    assert settings.apple_key_id == ""
    assert settings.apple_issuer_id == ""
    assert settings.apple_private_key_path is None


def test_production_requires_explicit_production_apple_environment() -> None:
    with pytest.raises(ValidationError, match="APPLE_ENVIRONMENT=Production"):
        Settings(_env_file=None, environment="production")


def test_production_requires_all_apple_identifiers(tmp_path: Path) -> None:
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_text("private key placeholder")

    with pytest.raises(ValidationError, match="requires all App Store credentials"):
        Settings(
            _env_file=None,
            environment="production",
            apple_environment="Production",
            apple_bundle_id="com.alexandremoreau.cloudbreak",
            apple_key_id="KEYID",
            apple_issuer_id="issuer-id",
            apple_private_key_path=key_path,
        )


def test_production_requires_a_readable_private_key_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="readable private key file"):
        Settings(
            _env_file=None,
            environment="production",
            apple_environment="Production",
            apple_bundle_id="com.alexandremoreau.cloudbreak",
            apple_app_id=123456789,
            apple_key_id="KEYID",
            apple_issuer_id="issuer-id",
            apple_private_key_path=tmp_path,
        )


def test_production_accepts_complete_readable_apple_configuration(tmp_path: Path) -> None:
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_text("private key placeholder")

    settings = Settings(
        _env_file=None,
        environment="production",
        apple_environment="Production",
        apple_bundle_id="com.alexandremoreau.cloudbreak",
        apple_app_id=123456789,
        apple_key_id="KEYID",
        apple_issuer_id="issuer-id",
        apple_private_key_path=key_path,
        expo_access_token="expo-test-token",
    )

    assert settings.apple_environment == "Production"
    assert settings.expo_access_token == "expo-test-token"


def _production_settings(key_path: Path, expo_access_token: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        apple_environment="Production",
        apple_bundle_id="com.alexandremoreau.cloudbreak",
        apple_app_id=123456789,
        apple_key_id="KEYID",
        apple_issuer_id="issuer-id",
        apple_private_key_path=key_path,
        expo_access_token=expo_access_token,
    )


@pytest.mark.parametrize("token", ["", "   "])
def test_production_requires_expo_access_token(tmp_path: Path, token: str) -> None:
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_text("private key placeholder")

    with pytest.raises(ValidationError, match="Production requires EXPO_ACCESS_TOKEN"):
        _production_settings(key_path, token)


def test_production_accepts_present_expo_access_token(tmp_path: Path) -> None:
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_text("private key placeholder")

    assert _production_settings(key_path, "expo-test-token").environment == "production"


def test_development_allows_empty_expo_access_token() -> None:
    settings = Settings(_env_file=None, environment="development", expo_access_token="")

    assert settings.expo_access_token == ""


def test_apple_environment_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, apple_environment="Xcode")  # type: ignore[arg-type]


def test_anonymous_purge_defaults() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anon_retention_days == 30
    assert settings.anon_purge_max_per_run == 200
