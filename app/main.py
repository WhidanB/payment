"""HTTP entrypoint / application factory.

Usage: uvicorn app.main:create_app --factory
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.adapters.inbound.http import routes_health
from app.logging_config import configure_logging


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
    )

    app.include_router(routes_health.router)

    return app
