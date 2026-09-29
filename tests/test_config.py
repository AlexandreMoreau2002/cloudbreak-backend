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
    )

    assert settings.apple_environment == "Production"


def test_apple_environment_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, apple_environment="Xcode")  # type: ignore[arg-type]
