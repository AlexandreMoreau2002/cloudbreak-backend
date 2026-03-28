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
