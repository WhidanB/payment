"""Runtime configuration, loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYMENT_", env_file=".env", extra="ignore")

    version: str = __version__

    # A transaction stays PENDING for this long before it is resolved.
    pending_delay_seconds: float = 15.0

    # Share of simulated transactions that are refused by the gateway.
    failure_rate: float = 0.05

    # Total number of transactions allowed per payment request (1 initial + retries).
    max_attempts: int = 2

    # Root log level (DEBUG also logs /health and the UI's list polling).
    log_level: str = "INFO"

    # PostgreSQL DSN (Neon in production). Unset = in-memory storage (lost on restart).
    database_url: str | None = None

    # Shared secret callers must send as `X-API-Key`. None = auth disabled (local/test).
    api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
