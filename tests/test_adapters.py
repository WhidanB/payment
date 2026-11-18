"""Outbound adapters in isolation."""

from __future__ import annotations

import asyncio
import logging
import random

import pytest

from app.adapters.outbound.asyncio_resolution_scheduler import AsyncioResolutionScheduler
from app.adapters.outbound.in_memory_payment_repository import InMemoryPaymentRepository
from app.adapters.outbound.simulated_payment_gateway import SimulatedPaymentGateway
from app.domain.model.enums import ReferenceType, SourceService
from app.domain.model.payment import PaymentReference, PaymentRequest

REF = PaymentReference(ReferenceType.BOOKING, "resa_1")


def new_payment(key: str) -> PaymentRequest:
    return PaymentRequest.create(
        idempotency_key=key,
        amount=100,
        currency="EUR",
        reference=REF,
        source_service=SourceService.BOOKING,
        max_attempts=2,
    )


# -- simulated gateway ------------------------------------------------------------------


async def authorize(gateway, reference, attempt=1):
    return await gateway.authorize(
        amount=100, currency="EUR", reference=reference, transaction_id="tx", attempt=attempt
    )


async def approvals(rate: float, n: int, seed: int = 1) -> int:
    gateway = SimulatedPaymentGateway(failure_rate=rate, rng=random.Random(seed))
    results = [await authorize(gateway, REF) for _ in range(n)]
    return sum(r.approved for r in results)


async def test_zero_failure_rate_always_approves():
    assert await approvals(0.0, 500) == 500


async def test_full_failure_rate_always_refuses():
    assert await approvals(1.0, 500) == 0


async def test_default_rate_refuses_about_five_percent():
    n = 20_000
    refused_share = 1 - await approvals(0.05, n, seed=42) / n
    assert 0.04 < refused_share < 0.06


async def test_refusal_carries_a_detail():
    gateway = SimulatedPaymentGateway(failure_rate=1.0)
    result = await authorize(gateway, REF)
    assert result.approved is False and result.detail == "simulated_refusal"


@pytest.mark.parametrize("rate", [-0.1, 1.5])
def test_failure_rate_must_be_a_probability(rate):
    with pytest.raises(ValueError):
        SimulatedPaymentGateway(failure_rate=rate)


# -- in-memory repository -----------------------------------------------------------------


async def test_repository_returns_copies_not_shared_state():
    repo = InMemoryPaymentRepository()
    payment = new_payment("k")
    await repo.save(payment)

    fetched = await repo.get(payment.id)
    fetched.mark_refused()

    assert (await repo.get(payment.id)).status.value == "PENDING"


async def test_repository_lookups_for_unknown_values_return_none():
    repo = InMemoryPaymentRepository()
    assert await repo.get("nope") is None
    assert await repo.find_by_idempotency_key("nope") is None
    assert await repo.list_recent(10) == []


async def test_repository_finds_by_key_and_lists_newest_first():
    repo = InMemoryPaymentRepository()
    saved = []
    for i in range(4):
        p = new_payment(f"k-{i}")
        await repo.save(p)
        saved.append(p)

    assert (await repo.find_by_idempotency_key("k-2")).id == saved[2].id
    assert [p.id for p in await repo.list_recent(2)] == [saved[3].id, saved[2].id]


# -- asyncio scheduler ----------------------------------------------------------------------


async def test_scheduler_runs_the_callback_after_the_delay():
    scheduler = AsyncioResolutionScheduler()
    ran = asyncio.Event()

    async def callback():
        ran.set()

    scheduler.schedule(0.02, callback)
    assert not ran.is_set()
    await asyncio.wait_for(ran.wait(), timeout=1)


async def test_scheduler_survives_a_failing_callback_and_logs_it(caplog):
    scheduler = AsyncioResolutionScheduler()
    later = asyncio.Event()

    async def boom():
        raise RuntimeError("kaboom")

    async def fine():
        later.set()

    with caplog.at_level(logging.ERROR, logger="payment.scheduler"):
        scheduler.schedule(0, boom)
        scheduler.schedule(0.01, fine)
        await asyncio.wait_for(later.wait(), timeout=1)

    assert any(r.message == "scheduler.callback_failed" for r in caplog.records)


async def test_scheduler_shutdown_cancels_pending_work():
    scheduler = AsyncioResolutionScheduler()
    ran = asyncio.Event()

    async def callback():
        ran.set()

    scheduler.schedule(5, callback)
    await scheduler.shutdown()
    await asyncio.sleep(0.05)

    assert not ran.is_set()


@pytest.mark.parametrize(
    "reference_id,attempt,approved",
    [
        ("demo-refuse-once", 1, False),
        ("demo-refuse-once", 2, True),
        ("demo-refuse-once-resa_42", 1, False),
        ("demo-refuse-always", 1, False),
        ("demo-refuse-always-stay_9", 2, False),
    ],
)
async def test_demo_reference_ids_force_a_deterministic_outcome(reference_id, attempt, approved):
    gateway = SimulatedPaymentGateway(failure_rate=0.0)  # random draw would always approve
    ref = PaymentReference(ReferenceType.BOOKING, reference_id)
    assert (await authorize(gateway, ref, attempt)).approved is approved


async def test_ordinary_reference_ids_ignore_the_attempt_number():
    gateway = SimulatedPaymentGateway(failure_rate=0.0)
    for attempt in (1, 2):
        assert (await authorize(gateway, REF, attempt)).approved is True
