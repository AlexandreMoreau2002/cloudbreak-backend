from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cloudbreak"
    redis_url: str = "redis://localhost:6379"
    weather_api_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    posthog_api_key: str = ""
    expo_access_token: str = ""
    environment: str = "development"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
