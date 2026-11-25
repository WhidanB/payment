"""GET /metrics: Prometheus counters for HTTP traffic and business operations."""

from __future__ import annotations

import time

from prometheus_client.parser import text_string_to_metric_families

from app.adapters.outbound.prometheus_metrics import PrometheusMetrics
from app.application.payment_service import PaymentService
from tests.conftest import ScriptedGateway

BODY = {
    "idempotency_key": "metrics-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


def sample(client, name: str, **labels: str) -> float:
    text = client.get("/metrics").text
    for family in text_string_to_metric_families(text):
        for s in family.samples:
            if s.name == name and labels.items() <= s.labels.items():
                return s.value
    return 0.0


def wait_settled(client, payment_id):
    for _ in range(100):
        if client.get(f"/payments/{payment_id}").json()["status"] != "PENDING":
            return
        time.sleep(0.02)
    raise AssertionError("payment still PENDING")


def test_metrics_is_prometheus_text_with_business_series_at_zero(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_requests_total counter" in r.text
    assert "# TYPE parking_operations_total counter" in r.text
    assert 'parking_operations_total{operation="payment",result="accepted"} 0.0' in r.text


def test_http_requests_are_counted_by_route_template_and_outcome(client):
    created = client.post("/payments", json=BODY).json()
    client.get(f"/payments/{created['payment_id']}")
    client.get("/payments/does-not-exist")
    client.get("/nowhere")

    assert sample(client, "http_requests_total", route="/payments", status="202") == 1
    assert (
        sample(client, "http_requests_total", route="/payments/{payment_id}", outcome="success")
        == 1
    )
    assert sample(client, "http_requests_total", route="/payments/{payment_id}", status="404") == 1
    assert sample(client, "http_requests_total", route="unmatched", outcome="error") == 1
    assert created["payment_id"] not in client.get("/metrics").text  # no per-id series


def test_payment_operations_follow_the_api(client):
    created = client.post("/payments", json=BODY).json()
    client.post("/payments", json=BODY)
    client.post("/payments", json={**BODY, "amount": 1})
    wait_settled(client, created["payment_id"])

    def ops(operation, outcome):
        return sample(client, "parking_operations_total", operation=operation, result=outcome)

    assert ops("payment", "requested") == 1
    assert ops("payment", "replayed") == 1
    assert ops("payment", "conflict") == 1
    assert ops("transaction", "accepted") == 1
    assert ops("payment", "accepted") == 1
    assert sample(client, "payment_accepted_amount_euros_total", reference_type="BOOKING") == 12.5
    assert sample(client, "payment_accepted_amount_euros_total", reference_type="PARKING_EXIT") == 0


async def test_refusal_retry_and_final_refusal_are_counted(repository, scheduler, command):
    metrics = PrometheusMetrics()
    service = PaymentService(
        repository,
        ScriptedGateway(default=False),
        scheduler,
        pending_delay_seconds=0.0,
        max_attempts=2,
        metrics=metrics,
    )
    await service.request_payment(command)
    await scheduler.run_all()

    def ops(operation, outcome):
        return metrics.registry.get_sample_value(
            "parking_operations_total", {"operation": operation, "result": outcome}
        )

    assert ops("transaction", "refused") == 2
    assert ops("payment", "retried") == 1
    assert ops("payment", "refused") == 1
    assert ops("payment", "accepted") == 0
    assert (
        metrics.registry.get_sample_value(
            "payment_accepted_amount_euros_total", {"reference_type": "BOOKING"}
        )
        == 0
    )  # refused payments collect nothing


def test_metrics_stays_open_when_the_api_key_is_enforced(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("PAYMENT_API_KEY", "secret-123")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        assert c.get("/metrics").status_code == 200
        assert c.post("/payments", json=BODY).status_code == 401
        assert sample(c, "http_requests_total", route="/payments", status="401") == 1
    get_settings.cache_clear()
