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


@lru_cache
def get_settings() -> Settings:
    return Settings()
