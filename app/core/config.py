from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cloudbreak"
    redis_url: str = "redis://localhost:6379"
    weather_api_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_publishable_key: str = ""
    supabase_jwt_jwks: str = ""
    supabase_db_password: str = ""
    posthog_api_key: str = ""
    expo_access_token: str = ""
    supabase_service_role_key: str = ""
    environment: str = "development"
    app_version: str = "1.0.0"
    apple_bundle_id: str = "com.alexandremoreau.cloudbreak"
    apple_environment: str = "Sandbox"
    apple_app_id: int | None = None
    apple_key_id: str = ""
    apple_issuer_id: str = ""
    apple_private_key_path: Path | None = None

    @model_validator(mode="after")
    def require_production_apple_identifiers(self) -> "Settings":
        if self.apple_environment == "Production" and (
            self.apple_app_id is None
            or not self.apple_key_id
            or not self.apple_issuer_id
            or self.apple_private_key_path is None
        ):
            raise ValueError("Production Apple verification requires all App Store credentials")
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
