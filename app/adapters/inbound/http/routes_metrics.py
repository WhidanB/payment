"""Prometheus scrape endpoint. Open like /health: it carries counters, no payment data."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.container import Container

router = APIRouter(tags=["monitoring"])


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    description=(
        "`http_requests_total` (method, route, status, outcome) and "
        "`parking_operations_total` (operation, outcome), in the Prometheus text format."
    ),
    response_class=Response,
)
async def metrics(request: Request) -> Response:
    container: Container = request.app.state.container
    return Response(container.metrics.render(), media_type=container.metrics.content_type)
