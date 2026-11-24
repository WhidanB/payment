"""Same behaviour expected from every PaymentRepository adapter (memory and PostgreSQL)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.adapters.outbound.in_memory_payment_repository import InMemoryPaymentRepository
from app.domain.model.enums import PaymentStatus, ReferenceType, SourceService, TransactionStatus
from app.domain.model.errors import IdempotencyKeyTaken
from app.domain.model.payment import PaymentReference, PaymentRequest


@pytest.fixture(params=["memory", "postgres"])
def repo(request):
    if request.param == "memory":
        return InMemoryPaymentRepository()
    return request.getfixturevalue("pg_repository")


def new_payment(key: str = "k", reference_id: str = "resa_1") -> PaymentRequest:
    return PaymentRequest.create(
        idempotency_key=key,
        amount=1250,
        currency="EUR",
        reference=PaymentReference(ReferenceType.PARKING_EXIT, reference_id),
        source_service=SourceService.ACCESS,
        max_attempts=2,
    )


async def test_round_trip_keeps_every_field(repo):
    payment = new_payment()
    first = payment.open_transaction()
    first.refuse()
    payment.open_transaction()
    await repo.save(payment)

    loaded = await repo.get(payment.id)

    assert loaded == payment
    assert [t.status for t in loaded.transactions] == [
        TransactionStatus.REFUSED,
        TransactionStatus.PENDING,
    ]
    assert loaded.transactions[0].resolved_at == first.resolved_at
    assert loaded.created_at.tzinfo is not None


async def test_saving_again_updates_status_and_adds_transactions(repo):
    payment = new_payment()
    tx = payment.open_transaction()
    await repo.save(payment)

    tx.accept()
    payment.mark_accepted()
    await repo.save(payment)

    loaded = await repo.get(payment.id)
    assert loaded.status is PaymentStatus.ACCEPTED
    assert loaded.transactions[0].status is TransactionStatus.ACCEPTED
    assert loaded.updated_at == payment.updated_at


@pytest.mark.parametrize("payment_id", ["unknown", "", "01a1edb2-fbf0-78d2-ad48-59cab7e54c0f"])
async def test_unknown_or_malformed_ids_return_none(repo, payment_id):
    assert await repo.get(payment_id) is None


async def test_find_by_idempotency_key(repo):
    payment = new_payment(key="booking:resa_1:create")
    await repo.save(payment)
    assert (await repo.find_by_idempotency_key("booking:resa_1:create")).id == payment.id
    assert await repo.find_by_idempotency_key("other") is None


async def test_a_key_cannot_belong_to_two_requests(repo):
    await repo.save(new_payment(key="same"))
    with pytest.raises(IdempotencyKeyTaken):
        await repo.save(new_payment(key="same"))
    assert len(await repo.list_recent(10)) == 1


async def test_list_recent_is_newest_first_and_limited(repo):
    saved = []
    for i in range(4):
        p = new_payment(key=f"k-{i}")
        p.created_at = p.created_at + timedelta(seconds=i)
        await repo.save(p)
        saved.append(p)

    assert [p.id for p in await repo.list_recent(3)] == [saved[3].id, saved[2].id, saved[1].id]
    assert await repo.list_recent(10) != []


async def test_find_with_pending_transactions(repo):
    settled = new_payment(key="settled")
    settled.open_transaction().accept()
    settled.mark_accepted()
    pending = new_payment(key="pending")
    pending.open_transaction()
    empty = new_payment(key="empty")
    for p in (settled, pending, empty):
        await repo.save(p)

    assert [p.id for p in await repo.find_with_pending_transactions()] == [pending.id]


async def test_loaded_objects_are_independent_copies(repo):
    payment = new_payment()
    payment.open_transaction()
    await repo.save(payment)

    loaded = await repo.get(payment.id)
    loaded.mark_refused()

    assert (await repo.get(payment.id)).status is PaymentStatus.PENDING


@pytest.mark.parametrize(
    "dsn,expected",
    [
        (
            "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        ),
        ("postgresql://u:p@host/db", "postgresql://u:p@host/db"),
        (
            "postgresql://u:p@host/db?sslmode=verify-full",
            "postgresql://u:p@host/db?sslmode=verify-full",
        ),
    ],
)
def test_neon_connection_strings_are_accepted_as_copied(dsn, expected):
    from app.adapters.outbound.postgres_payment_repository import asyncpg_dsn

    assert asyncpg_dsn(dsn) == expected
