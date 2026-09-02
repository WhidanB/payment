"""HTTP entrypoint / application factory.

Usage: uvicorn app.main:create_app --factory
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.adapters.inbound.http import routes_health, routes_payments
from app.adapters.outbound.asyncio_resolution_scheduler import AsyncioResolutionScheduler
from app.container import build_container
from app.logging_config import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    try:
        yield
    finally:
        scheduler = app.state.container.scheduler
        if isinstance(scheduler, AsyncioResolutionScheduler):
            await scheduler.shutdown()


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="Payment Service",
        version=__version__,
        summary="Parking fil rouge — payment microservice (simulated gateway).",
        description=(
            "Receives payment requests from the `booking` and `access` services, opens "
            "transactions to settle them and reports a status (PENDING / ACCEPTED / REFUSED). "
            "Swagger UI: /docs — OpenAPI: /openapi.json"
        ),
        lifespan=lifespan,
    )

    app.include_router(routes_health.router)
    app.include_router(routes_payments.router)

    return app
