"""
Centralized settings loaded from environment variables.

All tunable knobs live here. Never read os.environ directly from feature
code — import `settings` from this module instead.
"""
from functools import lru_cache
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    llm_model_primary: str = "google/gemini-2.5-flash-lite"
    llm_model_fallback: str = "openai/gpt-4o-mini"
    llm_model_vision: str = "google/gemini-2.5-flash-lite"

    # --- Database ---
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./vergabepilot.db")

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"

    # --- S3 / MinIO ---
    s3_endpoint: str = "http://localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    s3_bucket: str = "vergabepilot-documents"
    s3_region: str = "eu-central-1"

    # --- Phase 1 ---
    sandbox_timeout_seconds: int = 60
    sandbox_memory_mb: int = 512
    max_feedback_iterations: int = 5

    # --- Phase 2 ---
    cua_max_steps: int = 30
    cua_screenshot_dir: str = "/tmp/vergabepilot-screenshots"

    # --- Phase 3 ---
    downloads_dir: str = "/app/data/downloads"
    scraper_registry_path: str = "/app/data/scrapers"
    enable_fallback_cua: bool = True
    enable_route_learning: bool = True
    route_learning_max_clicks: int = 2
    versioning_check_interval_hours: int = 24

    # --- Misc ---
    log_level: str = "INFO"
    secret_key: str = "change-me"
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
