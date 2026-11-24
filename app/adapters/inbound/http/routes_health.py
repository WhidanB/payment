"""Liveness endpoint (common requirement for every microservice)."""

from __future__ import annotations

import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.adapters.outbound.postgres_payment_repository import PostgresPaymentRepository
from app.container import Container

router = APIRouter(tags=["health"])

_STARTED_AT = time.monotonic()


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    version: str
    uptime_seconds: float
    storage: Literal["postgres", "memory"]
    database: Literal["ok", "unreachable", "not_checked", "not_used"]
    pending_delay_seconds: float
    max_attempts: int
    failure_rate: float
    auth_enabled: bool


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service liveness",
    description=(
        "Cheap by default (does not touch the database, so Render's frequent probes do not "
        "keep Neon awake). `?deep=true` also checks the database connection."
    ),
)
async def health(request: Request, deep: bool = Query(False)) -> HealthResponse:
    container: Container = request.app.state.container
    settings = container.settings
    database = "not_used" if container.storage == "memory" else "not_checked"
    if deep and isinstance(container.repository, PostgresPaymentRepository):
        try:
            ok = await asyncio.wait_for(container.repository.ping(), timeout=5)
        except Exception:
            ok = False
        database = "ok" if ok else "unreachable"
    return HealthResponse(
        status="degraded" if database == "unreachable" else "ok",
        version=settings.version,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
        storage=container.storage,
        database=database,
        pending_delay_seconds=settings.pending_delay_seconds,
        max_attempts=settings.max_attempts,
        failure_rate=settings.failure_rate,
        auth_enabled=bool(settings.api_key),
    )
