"""Settings read from the environment (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "local"
    mongodb_uri: str = "mongodb://localhost:27017/?directConnection=true"
    mongodb_db: str = "firstlight"

    dd_env: str = "local"
    dd_version: str = "dev"
    dd_service: str = "firstlight"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash"
    gemini_embed_model: str = "gemini-embedding-2"

    webhook_secret: str = ""
    demo_code: str = ""

    firstlight_api_url: str = "http://localhost:8000"
    sim_farms: int = 50
    sim_ponds_per_farm: int = 4
    sim_batch_seconds: int = 10
    sim_farm_clock_start: str = "02:00"


@lru_cache
def get_settings() -> Settings:
    return Settings()
