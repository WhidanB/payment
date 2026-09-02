"""End-to-end HTTP test against the real app (simulated gateway forced to always approve)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

BODY = {
    "idempotency_key": "booking-api-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PAYMENT_PENDING_DELAY_SECONDS", "0")
    monkeypatch.setenv("PAYMENT_FAILURE_RATE", "0")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def _poll_until_settled(client, payment_id, attempts=50):
    for _ in range(attempts):
        body = client.get(f"/payments/{payment_id}").json()
        if body["status"] != "PENDING":
            return body
        time.sleep(0.02)
    raise AssertionError(f"payment {payment_id} never settled")


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"


def test_create_then_poll(client):
    created = client.post("/payments", json=BODY)
    assert created.status_code == 202
    payment_id = created.json()["payment_id"]
    assert created.json()["status"] == "PENDING"

    settled = _poll_until_settled(client, payment_id)
    assert settled["status"] == "ACCEPTED"
    assert settled["transactions"][0]["status"] == "ACCEPTED"


def test_idempotent_replay_returns_200(client):
    first = client.post("/payments", json=BODY)
    replay = client.post("/payments", json=BODY)
    assert replay.status_code == 200
    assert replay.json()["payment_id"] == first.json()["payment_id"]


def test_validation_error(client):
    bad = client.post("/payments", json={**BODY, "amount": 0})
    assert bad.status_code == 422


def test_unknown_payment_is_404(client):
    assert client.get("/payments/does-not-exist").status_code == 404
