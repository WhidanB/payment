"""What a real database must guarantee: restarts, resumed PENDING work, several instances."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.application.payment_service import PaymentService
from app.config import get_settings
from app.domain.model.enums import PaymentStatus
from app.domain.model.errors import IdempotencyConflict
from app.main import create_app
from tests.conftest import ManualScheduler, ScriptedGateway

BODY = {
    "idempotency_key": "persist-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


def service(repository, gateway=None, scheduler=None, delay=15.0):
    return PaymentService(
        repository,
        gateway or ScriptedGateway(),
        scheduler or ManualScheduler(),
        pending_delay_seconds=delay,
        max_attempts=2,
    )


# -- resuming PENDING work (any storage) ------------------------------------------------


async def test_resume_reschedules_only_the_remaining_delay(repository, command):
    first = service(repository)
    created = await first.request_payment(command)
    stored = await repository.get(created.payment.id)
    stored.transactions[0].created_at -= timedelta(seconds=10)  # restart 10 s later
    await repository.save(stored)

    scheduler = ManualScheduler()
    gateway = ScriptedGateway()
    restarted = service(repository, gateway, scheduler)
    assert await restarted.resume_pending() == 1
    assert 4.0 < scheduler.delays[0] <= 5.0

    await scheduler.run_all()
    assert (await restarted.get_payment(created.payment.id)).status is PaymentStatus.ACCEPTED
    assert gateway.calls == 1


async def test_overdue_transactions_resume_immediately(repository, command):
    created = await service(repository).request_payment(command)
    stored = await repository.get(created.payment.id)
    stored.transactions[0].created_at -= timedelta(minutes=30)
    await repository.save(stored)

    scheduler = ManualScheduler()
    await service(repository, scheduler=scheduler).resume_pending()

    assert scheduler.delays == [0.0]


async def test_nothing_to_resume_when_everything_is_settled(repository, command):
    first_scheduler = ManualScheduler()
    await service(repository, scheduler=first_scheduler).request_payment(command)
    await first_scheduler.run_all()

    assert await service(repository).resume_pending() == 0


# -- PostgreSQL --------------------------------------------------------------------------


async def test_two_instances_racing_on_the_same_key_create_one_request(pg_repository, command):
    # Two workers = two services with their own in-process locks, one shared database.
    a, b = service(pg_repository), service(pg_repository)

    results = await asyncio.gather(*(s.request_payment(command) for s in (a, b, a, b)))

    assert sum(r.created for r in results) == 1
    assert len({r.payment.id for r in results}) == 1
    assert len(await pg_repository.list_recent(10)) == 1


async def test_racing_instances_with_different_payloads_get_a_conflict(pg_repository, command):
    a, b = service(pg_repository), service(pg_repository)
    other = replace(command, amount=command.amount + 1)

    results = await asyncio.gather(
        a.request_payment(command), b.request_payment(other), return_exceptions=True
    )

    assert sum(isinstance(r, IdempotencyConflict) for r in results) == 1
    assert len(await pg_repository.list_recent(10)) == 1


@pytest.fixture
def pg_app_env(monkeypatch, pg_dsn, pg_repository):
    monkeypatch.setenv("PAYMENT_DATABASE_URL", pg_dsn)
    monkeypatch.setenv("PAYMENT_FAILURE_RATE", "0")
    monkeypatch.delenv("PAYMENT_API_KEY", raising=False)

    def start(delay: float) -> TestClient:
        monkeypatch.setenv("PAYMENT_PENDING_DELAY_SECONDS", str(delay))
        get_settings.cache_clear()
        return TestClient(create_app())

    yield start
    get_settings.cache_clear()


def wait_settled(client, payment_id):
    for _ in range(150):
        body = client.get(f"/payments/{payment_id}").json()
        if body["status"] != "PENDING":
            return body
        time.sleep(0.02)
    raise AssertionError("never settled")


def test_payments_survive_a_restart(pg_app_env):
    with pg_app_env(0) as first:
        created = first.post("/payments", json=BODY).json()
        wait_settled(first, created["payment_id"])

    with pg_app_env(0) as second:  # new process, same database
        again = second.get(f"/payments/{created['payment_id']}")
        replay = second.post("/payments", json=BODY)
        health = second.get("/health", params={"deep": True}).json()

    assert again.status_code == 200 and again.json()["status"] == "ACCEPTED"
    assert replay.status_code == 200 and replay.json()["payment_id"] == created["payment_id"]
    assert (health["storage"], health["database"], health["status"]) == ("postgres", "ok", "ok")


def test_a_payment_pending_at_shutdown_is_resolved_after_the_restart(pg_app_env):
    with pg_app_env(60) as first:  # stops long before the 60 s PENDING delay
        created = first.post("/payments", json=BODY).json()
    assert created["status"] == "PENDING"

    with pg_app_env(0) as second:
        settled = wait_settled(second, created["payment_id"])

    assert settled["status"] == "ACCEPTED"
    assert [t["status"] for t in settled["transactions"]] == ["ACCEPTED"]


def test_deep_health_reports_an_unreachable_database_as_degraded(pg_app_env):
    with pg_app_env(0) as client:
        client.portal.call(client.app.state.container.repository.close)
        body = client.get("/health", params={"deep": True}).json()
        shallow = client.get("/health").json()

    assert (body["status"], body["database"]) == ("degraded", "unreachable")
    assert (shallow["status"], shallow["database"]) == ("ok", "not_checked")


def test_shallow_health_never_touches_the_database(client):
    body = client.get("/health").json()
    assert (body["storage"], body["database"]) == ("memory", "not_used")
