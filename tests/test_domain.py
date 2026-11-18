"""Pure domain rules: no framework, no I/O."""

from __future__ import annotations

import pytest

from app.domain.model.enums import (
    PaymentStatus,
    ReferenceType,
    SourceService,
    TransactionStatus,
)
from app.domain.model.errors import InvalidPaymentRequest, TransactionAlreadyResolved
from app.domain.model.payment import PaymentReference, PaymentRequest
from app.domain.model.transaction import Transaction

REF = PaymentReference(ReferenceType.BOOKING, "resa_1")


def make(**overrides):
    args = dict(
        idempotency_key="k",
        amount=100,
        currency="EUR",
        reference=REF,
        source_service=SourceService.BOOKING,
        max_attempts=2,
    )
    args.update(overrides)
    return PaymentRequest.create(**args)


@pytest.mark.parametrize(
    "overrides",
    [
        {"idempotency_key": ""},
        {"idempotency_key": "  "},
        {"idempotency_key": "k" * 201},
        {"amount": 0},
        {"amount": -1},
        {"amount": 10_000_001},
        {"currency": "USD"},
        {"max_attempts": 0},
        {"reference": PaymentReference(ReferenceType.BOOKING, "")},
        {"reference": PaymentReference(ReferenceType.BOOKING, "r" * 101)},
    ],
)
def test_invariants_reject_invalid_requests(overrides):
    with pytest.raises(InvalidPaymentRequest):
        make(**overrides)


def test_new_request_is_pending_with_no_transaction_and_a_uuid_v7():
    payment = make()
    assert payment.status is PaymentStatus.PENDING
    assert payment.transactions == []
    assert payment.current_transaction is None
    assert payment.id[14] == "7"


def test_attempts_are_numbered_and_bounded_by_max_attempts():
    payment = make(max_attempts=2)

    first = payment.open_transaction()
    assert payment.can_retry() is True
    second = payment.open_transaction()

    assert (first.attempt, second.attempt) == (1, 2)
    assert payment.can_retry() is False
    assert payment.current_transaction is second
    assert payment.transaction_by_id(first.id) is first
    assert payment.transaction_by_id("unknown") is None


def test_transaction_ids_are_unique_and_time_ordered():
    payment = make(max_attempts=5)
    ids = [payment.open_transaction().id for _ in range(5)]
    assert len(set(ids)) == 5
    assert ids == sorted(ids)


def test_a_transaction_resolves_once():
    tx = Transaction.open("p", 1)
    tx.accept()
    assert tx.status is TransactionStatus.ACCEPTED and tx.resolved_at is not None
    with pytest.raises(TransactionAlreadyResolved):
        tx.refuse()
    with pytest.raises(TransactionAlreadyResolved):
        tx.accept()


def test_settling_updates_status_and_timestamp():
    payment = make()
    before = payment.updated_at
    payment.mark_refused()
    assert payment.status is PaymentStatus.REFUSED and payment.is_settled
    assert payment.updated_at >= before


def test_is_same_request_compares_every_business_field():
    payment = make()
    same = dict(amount=100, currency="EUR", reference=REF, source_service=SourceService.BOOKING)
    assert payment.is_same_request(**same)
    assert not payment.is_same_request(**{**same, "amount": 101})
    assert not payment.is_same_request(**{**same, "source_service": SourceService.ACCESS})
    assert not payment.is_same_request(
        **{**same, "reference": PaymentReference(ReferenceType.PARKING_EXIT, "resa_1")}
    )
