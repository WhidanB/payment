"""Business edge cases at service level: concurrency, provider failures, double resolution."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.adapters.outbound.in_memory_payment_repository import InMemoryPaymentRepository
from app.application.errors import PaymentNotFound
from app.domain.model.enums import PaymentStatus, TransactionStatus
from app.domain.model.errors import IdempotencyConflict
from app.domain.ports.payment_gateway import GatewayResult, PaymentGateway
from tests.conftest import ManualScheduler, ScriptedGateway


class YieldingRepository(InMemoryPaymentRepository):
    """Gives other coroutines a chance to run between read and write (exposes races)."""

    async def find_by_idempotency_key(self, key):
        await asyncio.sleep(0)
        return await super().find_by_idempotency_key(key)

    async def save(self, payment):
        await asyncio.sleep(0)
        await super().save(payment)


class FlakyGateway(PaymentGateway):
    """Raises for the first `failures` calls, then approves."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def authorize(self, *, amount, currency, reference) -> GatewayResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("provider unreachable")
        return GatewayResult(approved=True)


async def test_concurrent_requests_with_the_same_key_create_a_single_payment(command):
    from app.application.payment_service import PaymentService

    scheduler = ManualScheduler()
    gateway = ScriptedGateway()
    service = PaymentService(
        YieldingRepository(), gateway, scheduler, pending_delay_seconds=0, max_attempts=2
    )

    results = await asyncio.gather(*[service.request_payment(command) for _ in range(25)])
    await scheduler.run_all()

    assert sum(r.created for r in results) == 1
    assert len({r.payment.id for r in results}) == 1
    assert gateway.calls == 1  # one charge, not 25


async def test_concurrent_requests_with_different_keys_are_independent(make_service, command):
    service = make_service(ScriptedGateway())

    results = await asyncio.gather(
        *[service.request_payment(replace(command, idempotency_key=f"k-{i}")) for i in range(10)]
    )

    assert all(r.created for r in results)
    assert len({r.payment.id for r in results}) == 10


async def test_reusing_a_key_with_another_amount_raises_a_conflict(make_service, command):
    service = make_service(ScriptedGateway())
    await service.request_payment(command)

    with pytest.raises(IdempotencyConflict):
        await service.request_payment(replace(command, amount=command.amount + 1))


async def test_gateway_exception_is_treated_as_a_refusal_and_retried(
    make_service, scheduler, command
):
    gateway = FlakyGateway(failures=1)
    service = make_service(gateway)

    created = await service.request_payment(command)
    await scheduler.run_all()

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.ACCEPTED
    assert [t.status for t in settled.transactions] == [
        TransactionStatus.REFUSED,
        TransactionStatus.ACCEPTED,
    ]


async def test_persistent_gateway_outage_ends_refused_never_pending(
    make_service, scheduler, command
):
    service = make_service(FlakyGateway(failures=99))

    created = await service.request_payment(command)
    await scheduler.run_all()

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.REFUSED
    assert all(not t.is_pending for t in settled.transactions)


async def test_resolving_the_same_transaction_twice_charges_once(make_service, scheduler, command):
    gateway = ScriptedGateway()
    service = make_service(gateway)
    await service.request_payment(command)
    (callback,) = list(scheduler._pending)

    await callback()
    await callback()

    assert gateway.calls == 1


async def test_a_settled_payment_is_never_touched_by_a_late_resolution(
    make_service, scheduler, command
):
    gateway = ScriptedGateway(outcomes=[False, True])
    service = make_service(gateway)
    created = await service.request_payment(command)
    (first_callback,) = list(scheduler._pending)
    await scheduler.run_all()  # tx1 refused -> tx2 accepted -> settled

    await first_callback()  # stale callback fires again

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.ACCEPTED
    assert len(settled.transactions) == 2
    assert gateway.calls == 2


async def test_get_unknown_payment_raises(make_service):
    with pytest.raises(PaymentNotFound):
        await make_service(ScriptedGateway()).get_payment("nope")


async def test_list_payments_is_newest_first_and_respects_the_limit(make_service, command):
    service = make_service(ScriptedGateway())
    for i in range(5):
        await service.request_payment(replace(command, idempotency_key=f"k-{i}"))

    listed = await service.list_payments(limit=3)

    assert [p.idempotency_key for p in listed] == ["k-4", "k-3", "k-2"]


async def test_resolution_of_a_vanished_payment_is_a_no_op(
    make_service, scheduler, repository, command
):
    gateway = ScriptedGateway()
    service = make_service(gateway)
    created = await service.request_payment(command)
    del repository._by_id[created.payment.id]

    await scheduler.run_all()

    assert gateway.calls == 0
