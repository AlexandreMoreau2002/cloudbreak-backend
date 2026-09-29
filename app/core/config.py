from pathlib import Path
from typing import Literal

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
    apple_bundle_id: str = ""
    apple_environment: Literal["Sandbox", "Production"] = "Sandbox"
    apple_app_id: int | None = None
    apple_key_id: str = ""
    apple_issuer_id: str = ""
    apple_private_key_path: Path | None = None

    @model_validator(mode="after")
    def require_production_apple_identifiers(self) -> "Settings":
        if self.environment.lower() == "production" and self.apple_environment != "Production":
            raise ValueError("Production requires APPLE_ENVIRONMENT=Production")
        if self.environment.lower() != "production":
            return self

        if (
            not self.apple_bundle_id
            or self.apple_app_id is None
            or self.apple_app_id <= 0
            or not self.apple_key_id
            or not self.apple_issuer_id
            or self.apple_private_key_path is None
        ):
            raise ValueError("Production Apple verification requires all App Store credentials")
        try:
            with self.apple_private_key_path.open("rb"):
                pass
        except OSError as error:
            raise ValueError("Production requires a readable private key file") from error
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
