from app.domain.model.enums import PaymentStatus, TransactionStatus
from tests.conftest import ScriptedGateway


async def test_refusal_triggers_one_retry_then_accepts(make_service, scheduler, command):
    service = make_service(ScriptedGateway(outcomes=[False, True]))

    created = await service.request_payment(command)
    await scheduler.run_all()

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.ACCEPTED
    assert [t.status for t in settled.transactions] == [
        TransactionStatus.REFUSED,
        TransactionStatus.ACCEPTED,
    ]
    assert [t.attempt for t in settled.transactions] == [1, 2]


async def test_two_refusals_settle_the_request_as_refused(make_service, scheduler, command):
    gateway = ScriptedGateway(default=False)
    service = make_service(gateway)

    created = await service.request_payment(command)
    await scheduler.run_all()

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.REFUSED
    assert len(settled.transactions) == 2
    assert all(t.status is TransactionStatus.REFUSED for t in settled.transactions)
    assert gateway.calls == 2  # exactly one retry, no more


async def test_no_retry_when_max_attempts_is_one(make_service, scheduler, command):
    service = make_service(ScriptedGateway(default=False), max_attempts=1)

    created = await service.request_payment(command)
    await scheduler.run_all()

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.REFUSED
    assert len(settled.transactions) == 1
