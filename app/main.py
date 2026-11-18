"""HTTP entrypoint / application factory.

Usage: uvicorn app.main:create_app --factory
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.adapters.inbound.http import routes_health, routes_payments, routes_ui
from app.adapters.outbound.asyncio_resolution_scheduler import AsyncioResolutionScheduler
from app.config import get_settings
from app.container import build_container
from app.domain.model.ids import new_id
from app.logging_config import configure_logging, request_id_var

logger = logging.getLogger("payment.http")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_QUIET_PATHS = {"/health"}  # polled by Render / the UI: logged at DEBUG only


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
    configure_logging(get_settings().log_level.upper())

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

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID_RE.match(supplied) else new_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:  # noqa: BLE001 - last-resort handler, keeps the 500 body JSON
            logger.exception("http.unhandled_error")
            response = JSONResponse(
                {"detail": "internal server error", "request_id": request_id}, status_code=500
            )
        finally:
            polling = request.url.path in _QUIET_PATHS or (
                request.method == "GET" and request.url.path == "/payments"
            )
            logger.log(
                logging.DEBUG if polling else logging.INFO,
                "http.request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(routes_health.router)
    app.include_router(routes_payments.router)
    app.include_router(routes_ui.router)

    return app
