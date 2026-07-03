"""
Centralized settings loaded from environment variables.

All tunable knobs live here. Never read os.environ directly from feature
code — import `settings` from this module instead.

SECRET REQUIREMENTS
-------------------
The following variables MUST be set in the environment (or .env file) before
the application will start. Startup will abort with a clear error if they are
missing or set to their insecure development defaults:

  SECRET_KEY           — Flask/JWT signing key (min 32 chars)
  MINIO_ROOT_USER      — MinIO access key
  MINIO_ROOT_PASSWORD  — MinIO secret key (min 8 chars)
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {"change-me", "changeme", "secret", "password", "admin", "minioadmin"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    llm_model_primary: str = "google/gemini-2.5-flash-lite"
    llm_model_fallback: str = "google/gemini-2.5-flash-lite"
    llm_model_vision: str = "google/gemini-2.5-flash-lite"

    # --- Database ---
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./vergabepilot.db")

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"

    # --- S3 / MinIO ---
    s3_endpoint: str = "http://localhost:9000"
    minio_root_user: str = ""
    minio_root_password: str = ""
    s3_bucket: str = "vergabepilot-documents"
    s3_region: str = "eu-central-1"

    # --- Phase 1 ---
    # 90s with a 75s in-scraper deadline: the prompt tells generated code to
    # self-terminate at 75s and return partial results, so the sandbox kill is
    # a backstop, not the norm. The previous 45s (with a prompt that promised
    # 60s!) killed multi-step JS portals before result.json was written —
    # the benchmark's biggest crash bucket.
    sandbox_timeout_seconds: int = 90
    sandbox_memory_mb: int = 512
    max_feedback_iterations: int = 3
    # Per-URL hard cap for benchmark/evaluation runs (LLM + sandbox + retries).
    evaluation_run_timeout_seconds: int = 600

    # --- Phase 2 ---
    cua_max_steps: int = 15
    # The CUA is stochastic — the same portal can succeed on a second attempt
    # (benchmarks showed run-to-run variance is the main driver of CUA misses).
    # Deterministic walls (login/CAPTCHA/404/expired) are never retried.
    cua_attempts: int = 2
    cua_screenshot_dir: str = "/tmp/vergabepilot-screenshots"

    # --- Phase 3 ---
    downloads_dir: str = "/app/data/downloads"
    scraper_registry_path: str = "/app/data/scrapers"
    enable_fallback_cua: bool = True
    enable_route_learning: bool = False
    route_learning_max_clicks: int = 2
    # When the CUA succeeds after every cheaper strategy failed, learn a
    # replayable route and persist it so the LEARNED_ROUTE strategy can serve
    # future visits to the domain cheaply (no LLM, no vision, no full CUA).
    enable_cua_route_learning: bool = True
    versioning_check_interval_hours: int = 24

    # --- Parallelism & Scalability ---
    job_concurrency: int = 8
    llm_global_concurrency: int = 2
    domain_llm_lock_ttl: int = 360
    job_chunk_size: int = 50

    # --- Security ---
    secret_key: str = ""
    # Per-IP request cap for the public (unauthenticated) tender directory, per minute.
    public_rate_limit_per_minute: int = 60

    # --- Misc ---
    log_level: str = "INFO"
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        """Abort startup when secrets are missing or insecure."""
        errors: list[str] = []

        # secret_key
        if not self.secret_key:
            errors.append(
                "SECRET_KEY is not set. "
                "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
        elif self.secret_key.lower() in _INSECURE_DEFAULTS or len(self.secret_key) < 16:
            errors.append(
                f"SECRET_KEY='{self.secret_key[:8]}...' is insecure. "
                "Set a random 32+ character value."
            )

        # MinIO credentials
        if not self.minio_root_user:
            errors.append("MINIO_ROOT_USER is not set.")
        elif self.minio_root_user.lower() in _INSECURE_DEFAULTS:
            errors.append(
                f"MINIO_ROOT_USER='{self.minio_root_user}' is an insecure default. "
                "Set a real username."
            )

        if not self.minio_root_password:
            errors.append("MINIO_ROOT_PASSWORD is not set.")
        elif self.minio_root_password.lower() in _INSECURE_DEFAULTS or len(self.minio_root_password) < 8:
            errors.append(
                f"MINIO_ROOT_PASSWORD is insecure or too short (min 8 chars). "
                "Set a strong password."
            )

        if errors:
            _env = os.getenv("VERGABEPILOT_ENV", "").lower()
            if _env in ("production", "prod", "staging"):
                # Hard fail in production
                print("\n[VERGABEPILOT STARTUP ERROR] Insecure configuration:\n", file=sys.stderr)
                for e in errors:
                    print(f"  ✗  {e}", file=sys.stderr)
                print(
                    "\nSet these environment variables before starting the service.\n",
                    file=sys.stderr,
                )
                sys.exit(1)
            else:
                # Warn loudly in development but don't abort
                import warnings
                msg = (
                    "[VERGABEPILOT] Insecure configuration detected — "
                    "do NOT deploy to production with these settings:\n  "
                    + "\n  ".join(errors)
                )
                warnings.warn(msg, stacklevel=2)

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
