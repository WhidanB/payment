"""Domain errors."""

from __future__ import annotations


class PaymentDomainError(Exception):
    """Base class for domain rule violations."""


class InvalidPaymentRequest(PaymentDomainError):
    """The payment request data breaks a domain invariant (bad amount, currency...)."""


class TransactionAlreadyResolved(PaymentDomainError):
    """Attempt to resolve a transaction that is no longer pending."""


class IdempotencyConflict(PaymentDomainError):
    """An idempotency key was reused with a different payload."""

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            f"idempotency_key {idempotency_key!r} was already used with a different request"
        )
        self.idempotency_key = idempotency_key
