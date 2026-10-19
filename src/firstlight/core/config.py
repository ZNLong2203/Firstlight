"""Settings read from the environment (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "local"
    mongodb_uri: str = "mongodb://localhost:27017/?directConnection=true"
    mongodb_db: str = "firstlight"
    mongodb_timeout_ms: int = 5000
    mongodb_socket_timeout_ms: int = 20000
    # Share of queries MongoDB samples into $queryStats, which Datadog Database Monitoring reads for its
    # query metrics. 0 leaves the server's setting alone. The setting does not survive a mongod restart,
    # so the API applies it on every start.
    mongodb_query_stats_rate: float = 0.0

    dd_env: str = "local"
    dd_version: str = "dev"
    dd_service: str = "firstlight"
    dd_trace_enabled: bool = False
    # For the brain's notebooks: Datadog's API takes both keys. The Agent needs neither of them from here.
    dd_site: str = ""
    dd_api_key: str = ""
    dd_app_key: str = ""
    dd_agent_host: str = "localhost"
    dd_dogstatsd_port: int = 8125

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash"
    gemini_embed_model: str = "gemini-embedding-2"
    # Vertex AI (Gemini on Google Cloud) instead of the Gemini Developer API, which refuses some hosting
    # IPs by location. Either an express-mode API key in GEMINI_API_KEY, or a service account (base64 JSON).
    gemini_vertex: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "asia-southeast1"
    google_service_account_b64: str = ""

    webhook_secret: str = ""
    gateway_token: str = ""
    demo_code: str = ""
    # "id" claims each batch by its id. Release 1.4 ships "fields": it looks batches up by gateway and
    # sequence number, which no index covers. That is the regression scenario 3 deploys and rolls back.
    ingest_duplicate_check: Literal["id", "fields"] = "id"

    # Telegram: messages to the farm owner with an "acknowledged" button; off until a bot exists.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""
    public_host: str = "localhost"  # links in messages open the console here

    firstlight_api_url: str = "http://localhost:8000"
    edge_control_url: str = "http://localhost:9000"  # the API reaches the simulator's control port here
    edge_control_port: int = 9000
    sim_farms: int = 50
    sim_batch_seconds: int = 10
    # Farm clock = UTC + offset: Vietnam time. The simulated ponds follow the real day and night there.
    sim_farm_clock_offset_hours: float = 7.0

    # A pond counts as recovered after DO stays at or above 4 mg/L, not falling, for this long.
    # Two minutes keeps a live demo moving; a farm would use ten.
    recovery_stable_min: float = 2.0
    escalate_after_min: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
