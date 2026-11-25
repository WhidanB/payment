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
from app.adapters.inbound.http import routes_health, routes_metrics, routes_payments, routes_ui
from app.config import get_settings
from app.container import build_container
from app.domain.model.ids import new_id
from app.logging_config import configure_logging, correlation_id_var

logger = logging.getLogger("payment.http")

_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_QUIET_PATHS = {"/health", "/metrics"}  # polled by Render / the UI / Prometheus: DEBUG only


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = await build_container()
    app.state.container = container
    resumed = await container.payment_service.resume_pending()
    logger.info("app.started", extra={"storage": container.storage, "resumed": resumed})
    try:
        yield
    finally:
        await container.close()


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
        supplied = request.headers.get("x-correlation-id", "")
        correlation_id = supplied if _CORRELATION_ID_RE.match(supplied) else new_id()
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception("http.unhandled_error")
            response = JSONResponse(
                {"detail": "internal server error", "correlation_id": correlation_id},
                status_code=500,
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
            # Route template, not the raw path: one series per endpoint, not per payment id.
            route = request.scope.get("route")
            request.app.state.container.metrics.observe_http(
                method=request.method,
                route=getattr(route, "path", "unmatched"),
                status=status_code,
            )
            correlation_id_var.reset(token)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    app.include_router(routes_health.router)
    app.include_router(routes_payments.router)
    app.include_router(routes_ui.router)
    app.include_router(routes_metrics.router)

    return app
