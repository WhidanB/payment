from app.domain.model.enums import PaymentStatus, TransactionStatus
from tests.conftest import ScriptedGateway


async def test_request_starts_pending_with_one_transaction(make_service, command):
    service = make_service(ScriptedGateway())

    result = await service.request_payment(command)

    assert result.payment.status is PaymentStatus.PENDING
    assert len(result.payment.transactions) == 1
    assert result.payment.transactions[0].attempt == 1
    assert result.payment.transactions[0].status is TransactionStatus.PENDING


async def test_pending_resolves_to_accepted(make_service, scheduler, repository, command):
    service = make_service(ScriptedGateway(outcomes=[True]))

    created = await service.request_payment(command)
    await scheduler.run_all()

    settled = await service.get_payment(created.payment.id)
    assert settled.status is PaymentStatus.ACCEPTED
    assert [t.status for t in settled.transactions] == [TransactionStatus.ACCEPTED]
    assert settled.transactions[0].resolved_at is not None


async def test_uuid_v7_identifiers(make_service, command):
    service = make_service(ScriptedGateway())

    payment = (await service.request_payment(command)).payment

    # UUID v7: version nibble is '7'
    assert payment.id[14] == "7"
    assert payment.transactions[0].id[14] == "7"
