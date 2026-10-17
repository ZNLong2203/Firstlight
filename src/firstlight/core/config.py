"""Settings read from the environment (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "local"
    mongodb_uri: str = "mongodb://localhost:27017/?directConnection=true"
    mongodb_db: str = "firstlight"
    mongodb_timeout_ms: int = 5000

    dd_env: str = "local"
    dd_version: str = "dev"
    dd_service: str = "firstlight"
    dd_trace_enabled: bool = False
    dd_agent_host: str = "localhost"
    dd_dogstatsd_port: int = 8125

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash"
    gemini_embed_model: str = "gemini-embedding-2"

    webhook_secret: str = ""
    gateway_token: str = ""
    demo_code: str = ""

    firstlight_api_url: str = "http://localhost:8000"
    edge_control_url: str = "http://localhost:9000"  # the API reaches the simulator's control port here
    edge_control_port: int = 9000
    sim_farms: int = 50
    sim_ponds_per_farm: int = 4
    sim_batch_seconds: int = 10
    # Farm clock = UTC + offset. -5 puts 02:00 on the farm at 14:00 in Vietnam, in time for an afternoon demo.
    sim_farm_clock_offset_hours: float = -5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
