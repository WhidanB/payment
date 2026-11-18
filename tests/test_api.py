"""End-to-end HTTP test against the real app (simulated gateway forced to always approve)."""

from __future__ import annotations

import time

import pytest

BODY = {
    "idempotency_key": "booking-api-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


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


def test_list_payments_newest_first(client):
    first = client.post("/payments", json={**BODY, "idempotency_key": "list-1"}).json()
    second = client.post("/payments", json={**BODY, "idempotency_key": "list-2"}).json()

    listed = client.get("/payments", params={"limit": 10}).json()

    assert [p["payment_id"] for p in listed[:2]] == [second["payment_id"], first["payment_id"]]
    assert listed[0]["idempotency_key"] == "list-2"


def test_list_payments_validates_limit(client):
    assert client.get("/payments", params={"limit": 0}).status_code == 422


def test_ui_is_served_and_root_redirects(client):
    page = client.get("/ui")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Payment" in page.text

    root = client.get("/", follow_redirects=False)
    assert root.status_code in (302, 307)
    assert root.headers["location"] == "/ui"


def test_health_exposes_ui_config(client):
    body = client.get("/health").json()
    assert body["pending_delay_seconds"] == 0
    assert body["max_attempts"] == 2
    assert body["auth_enabled"] is False


@pytest.mark.parametrize(
    "reference_id,final,chain",
    [
        ("demo-refuse-once-resa_1", "ACCEPTED", ["REFUSED", "ACCEPTED"]),
        ("demo-refuse-always-resa_1", "REFUSED", ["REFUSED", "REFUSED"]),
    ],
)
def test_demo_scenarios_show_the_refusal_and_its_automatic_retry(
    client, reference_id, final, chain
):
    body = {
        **BODY,
        "idempotency_key": reference_id,
        "reference": {"type": "BOOKING", "id": reference_id},
    }
    created = client.post("/payments", json=body)

    settled = _poll_until_settled(client, created.json()["payment_id"])

    assert settled["status"] == final
    assert [t["status"] for t in settled["transactions"]] == chain
    assert [t["attempt"] for t in settled["transactions"]] == [1, 2]
