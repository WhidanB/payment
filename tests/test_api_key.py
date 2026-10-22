"""X-API-Key enforcement on /payments. /health always stays open."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

BODY = {
    "idempotency_key": "booking-apikey-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


@pytest.fixture
def secured_client(monkeypatch):
    monkeypatch.setenv("PAYMENT_PENDING_DELAY_SECONDS", "0")
    monkeypatch.setenv("PAYMENT_FAILURE_RATE", "0")
    monkeypatch.setenv("PAYMENT_API_KEY", "secret-123")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_health_is_open_without_a_key(secured_client):
    assert secured_client.get("/health").status_code == 200


def test_payments_rejects_missing_key(secured_client):
    r = secured_client.post("/payments", json=BODY)
    assert r.status_code == 401


def test_payments_rejects_wrong_key(secured_client):
    r = secured_client.post("/payments", json=BODY, headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_payments_accepts_correct_key(secured_client):
    r = secured_client.post("/payments", json=BODY, headers={"X-API-Key": "secret-123"})
    assert r.status_code == 202
    payment_id = r.json()["payment_id"]

    unauthorized_get = secured_client.get(f"/payments/{payment_id}")
    assert unauthorized_get.status_code == 401

    authorized_get = secured_client.get(
        f"/payments/{payment_id}", headers={"X-API-Key": "secret-123"}
    )
    assert authorized_get.status_code == 200


def test_auth_is_disabled_when_no_key_is_configured(monkeypatch):
    monkeypatch.delenv("PAYMENT_API_KEY", raising=False)
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        assert c.post("/payments", json=BODY).status_code == 202
    get_settings.cache_clear()
