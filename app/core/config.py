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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
