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


@router.get("/health", response_model=HealthResponse, summary="Service liveness")
def health() -> HealthResponse:
    return HealthResponse(
        version=get_settings().version,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
    )
