"""Logs must be exploitable: JSON lines, one event per state change, linked by request id."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

BODY = {
    "idempotency_key": "log-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


def log_lines(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def wait_settled(client, payment_id, headers=None):
    for _ in range(100):
        if client.get(f"/payments/{payment_id}", headers=headers).json()["status"] != "PENDING":
            return
        time.sleep(0.02)
    raise AssertionError("never settled")


def test_every_log_line_is_valid_json_with_the_standard_fields(capsys, client):
    client.post("/payments", json=BODY)
    lines = log_lines(capsys)
    assert lines, "no log output captured"
    for line in lines:
        assert {"timestamp", "level", "logger", "message"} <= line.keys()


def test_payment_lifecycle_events_share_the_originating_request_id(capsys, client):
    created = client.post("/payments", json=BODY)
    request_id = created.headers["X-Request-ID"]
    wait_settled(client, created.json()["payment_id"])

    lines = [line for line in log_lines(capsys) if line.get("request_id") == request_id]
    events = [line["message"] for line in lines]

    for expected in (
        "payment.requested",
        "transaction.created",
        "gateway.authorize",
        "transaction.accepted",
        "payment.accepted",
        "http.request",
    ):
        assert expected in events, events
    accepted = next(line for line in lines if line["message"] == "transaction.accepted")
    assert accepted["payment_id"] == created.json()["payment_id"]
    assert accepted["transaction_id"] == created.json()["transactions"][0]["transaction_id"]
    assert accepted["attempt"] == 1 and accepted["amount"] == 1250


def test_http_request_line_has_method_path_status_and_duration(capsys, client):
    client.post("/payments", json=BODY)
    line = next(line for line in log_lines(capsys) if line["message"] == "http.request")
    assert (line["method"], line["path"], line["status"]) == ("POST", "/payments", 202)
    assert line["duration_ms"] >= 0


def test_health_and_list_polling_are_not_logged_at_info(capsys, client):
    client.get("/health")
    client.get("/payments")
    assert [line for line in log_lines(capsys) if line["message"] == "http.request"] == []


def test_idempotent_replay_and_conflict_are_logged(capsys, client):
    client.post("/payments", json=BODY)
    client.post("/payments", json=BODY)
    client.post("/payments", json={**BODY, "amount": 1})
    messages = {(line["message"], line["level"]) for line in log_lines(capsys)}
    assert ("payment.idempotent_hit", "INFO") in messages
    assert ("payment.idempotency_conflict", "WARNING") in messages


def test_request_id_is_generated_echoed_or_replaced(client):
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 36

    assert client.get("/health", headers={"X-Request-ID": "trace-abc.123"}).headers[
        "X-Request-ID"
    ] == "trace-abc.123"

    replaced = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"}).headers[
        "X-Request-ID"
    ]
    assert replaced != "bad id\twith spaces" and len(replaced) == 36


def test_retry_and_refusal_are_logged_with_the_attempt_number(capsys, monkeypatch):
    monkeypatch.setenv("PAYMENT_PENDING_DELAY_SECONDS", "0")
    monkeypatch.setenv("PAYMENT_FAILURE_RATE", "1")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        created = c.post("/payments", json=BODY).json()
        wait_settled(c, created["payment_id"])
    get_settings.cache_clear()

    lines = log_lines(capsys)
    refused = [line for line in lines if line["message"] == "transaction.refused"]
    assert [line["attempt"] for line in refused] == [1, 2]
    assert any(line["message"] == "payment.retry_scheduled" for line in lines)
    assert any(line["message"] == "payment.refused" for line in lines)


def test_unhandled_errors_return_a_json_500_with_the_request_id(capsys, monkeypatch):
    monkeypatch.setenv("PAYMENT_PENDING_DELAY_SECONDS", "0")
    get_settings.cache_clear()
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("unexpected")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    get_settings.cache_clear()

    assert r.status_code == 500
    assert r.json()["request_id"] == r.headers["X-Request-ID"]
    lines = log_lines(capsys)
    error = next(line for line in lines if line["message"] == "http.unhandled_error")
    assert "RuntimeError" in error["exception"] and error["request_id"] == r.headers["X-Request-ID"]
    assert next(line for line in lines if line["message"] == "http.request")["status"] == 500


def test_the_api_key_is_never_logged(capsys, monkeypatch):
    monkeypatch.setenv("PAYMENT_PENDING_DELAY_SECONDS", "0")
    monkeypatch.setenv("PAYMENT_API_KEY", "super-secret-key")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        headers = {"X-API-Key": "super-secret-key"}
        created = c.post("/payments", json=BODY, headers=headers)
        wait_settled(c, created.json()["payment_id"], headers)
        c.post("/payments", json=BODY, headers={"X-API-Key": "wrong-guess"})
    get_settings.cache_clear()

    out = capsys.readouterr().out
    assert "super-secret-key" not in out and "wrong-guess" not in out


@pytest.mark.parametrize("level,visible", [("INFO", False), ("DEBUG", True)])
def test_log_level_controls_polling_noise(capsys, monkeypatch, level, visible):
    monkeypatch.setenv("PAYMENT_LOG_LEVEL", level)
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        c.get("/health")
    get_settings.cache_clear()
    seen = any(line["message"] == "http.request" for line in log_lines(capsys))
    assert seen is visible
