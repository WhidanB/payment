"""Prometheus exposition of HTTP traffic and business operations (GET /metrics).

Each instance owns its registry, so several apps (tests) never collide on metric names.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)

from app.domain.model.enums import ReferenceType
from app.domain.ports.operation_metrics import Operation, OperationMetrics, Outcome

# Series that exist from startup at 0, so graphs and rate() work before the first payment.
_KNOWN_OPERATIONS: dict[str, tuple[str, ...]] = {
    "payment": ("requested", "replayed", "conflict", "retried", "accepted", "refused"),
    "transaction": ("accepted", "refused"),
}


class PrometheusMetrics(OperationMetrics):
    content_type = CONTENT_TYPE_LATEST

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        self._http_requests = Counter(
            "http_requests",
            "HTTP requests handled, by route template and outcome (error = status >= 400).",
            ["method", "route", "status", "outcome"],
            registry=self.registry,
        )
        self._operations = Counter(
            "parking_operations",
            "Business operations of the payment service.",
            ["operation", "result"],  # same label names as booking, access, parking
            registry=self.registry,
        )
        self._accepted_amount = Counter(
            "payment_accepted_amount_euros",
            "Money collected by accepted payments, in euros, by what was paid for.",
            ["reference_type"],
            registry=self.registry,
        )
        for reference_type in ReferenceType:
            self._accepted_amount.labels(reference_type=reference_type.value)
        for operation, outcomes in _KNOWN_OPERATIONS.items():
            for outcome in outcomes:
                self._operations.labels(operation=operation, result=outcome)

    def observe_http(self, *, method: str, route: str, status: int) -> None:
        self._http_requests.labels(
            method=method,
            route=route,
            status=str(status),
            outcome="error" if status >= 400 else "success",
        ).inc()

    def record(self, operation: Operation, outcome: Outcome) -> None:
        self._operations.labels(operation=operation, result=outcome).inc()

    def record_accepted_amount(self, *, amount: int, reference_type: str) -> None:
        self._accepted_amount.labels(reference_type=reference_type).inc(amount / 100)

    def render(self) -> bytes:
        return generate_latest(self.registry)
