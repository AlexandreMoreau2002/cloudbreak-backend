from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

PROD_INFRA = {
    "database_url": "postgresql+asyncpg://app:pw@db.internal:5432/cloudbreak",
    "redis_url": "redis://redis.internal:6379",
    "supabase_url": "https://example.supabase.co",
    "supabase_jwt_jwks": '{"keys": []}',
    "supabase_service_role_key": "service-role-test",
    "internal_cron_secret": "x" * 32,
}


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
        **PROD_INFRA,
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
        **PROD_INFRA,
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


def _prod(key_path: Path, **overrides: str) -> Settings:
    values = {**PROD_INFRA, **overrides}
    return Settings(
        _env_file=None,
        environment="production",
        apple_environment="Production",
        apple_bundle_id="com.alexandremoreau.cloudbreak",
        apple_app_id=123456789,
        apple_key_id="KEYID",
        apple_issuer_id="issuer-id",
        apple_private_key_path=key_path,
        expo_access_token="expo-test-token",
        **values,  # type: ignore[arg-type]
    )


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "AuthKey_TEST.p8"
    path.write_text("private key placeholder")
    return path


def test_production_accepts_complete_infrastructure(key_file: Path) -> None:
    assert _prod(key_file).environment == "production"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("database_url", "postgresql+asyncpg://p:s3cret@localhost:5432/db", "DATABASE_URL"),
        ("database_url", "postgresql+asyncpg://p:s3cret@127.0.0.1:5432/db", "DATABASE_URL"),
        ("redis_url", "redis://localhost:6379", "REDIS_URL"),
        ("redis_url", "redis://127.0.0.1:6379", "REDIS_URL"),
        ("supabase_url", "", "SUPABASE_URL"),
        ("supabase_jwt_jwks", "", "SUPABASE_JWT_JWKS"),
        ("supabase_service_role_key", "", "SUPABASE_SERVICE_ROLE_KEY"),
        ("internal_cron_secret", "", "INTERNAL_CRON_SECRET"),
        ("internal_cron_secret", "y" * 31, "INTERNAL_CRON_SECRET"),
    ],
)
def test_production_rejects_unsafe_infrastructure(
    key_file: Path, field: str, value: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message) as error:
        _prod(key_file, **{field: value})

    assert value not in str(error.value) or value == ""


def test_production_error_never_prints_secret_values(key_file: Path) -> None:
    with pytest.raises(ValidationError) as error:
        _prod(key_file, database_url="postgresql+asyncpg://p:s3cretpw@localhost:5432/db")

    assert "s3cretpw" not in str(error.value)


def test_development_allows_local_infrastructure() -> None:
    settings = Settings(_env_file=None, environment="development")

    assert "localhost" in settings.database_url
    assert settings.internal_cron_secret == ""
