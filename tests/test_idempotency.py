from dataclasses import replace

from app.domain.model.enums import PaymentStatus
from tests.conftest import ScriptedGateway


async def test_same_key_returns_same_request_without_new_transaction(make_service, command):
    service = make_service(ScriptedGateway())

    first = await service.request_payment(command)
    second = await service.request_payment(command)

    assert first.created is True
    assert second.created is False
    assert second.payment.id == first.payment.id
    assert len(second.payment.transactions) == 1


async def test_replay_after_settlement_does_not_recharge(make_service, scheduler, command):
    gateway = ScriptedGateway(default=True)
    service = make_service(gateway)

    await service.request_payment(command)
    await scheduler.run_all()
    calls_after_settle = gateway.calls

    replay = await service.request_payment(command)

    assert replay.created is False
    assert replay.payment.status is PaymentStatus.ACCEPTED
    assert gateway.calls == calls_after_settle  # no extra authorize call


async def test_different_key_creates_a_distinct_request(make_service, command):
    service = make_service(ScriptedGateway())

    a = await service.request_payment(command)
    b = await service.request_payment(replace(command, idempotency_key="booking-2"))

    assert a.payment.id != b.payment.id
