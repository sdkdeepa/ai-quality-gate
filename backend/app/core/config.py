from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables (prefix AQG_)."""

    model_config = SettingsConfigDict(env_prefix="AQG_", env_file=".env", extra="ignore")

    app_name: str = "AI Quality Gate"
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
