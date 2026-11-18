"""Liveness endpoint (common requirement for every microservice)."""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])

_STARTED_AT = time.monotonic()


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    uptime_seconds: float
    pending_delay_seconds: float
    max_attempts: int
    failure_rate: float
    auth_enabled: bool


@router.get("/health", response_model=HealthResponse, summary="Service liveness")
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=settings.version,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
        pending_delay_seconds=settings.pending_delay_seconds,
        max_attempts=settings.max_attempts,
        failure_rate=settings.failure_rate,
        auth_enabled=bool(settings.api_key),
    )
