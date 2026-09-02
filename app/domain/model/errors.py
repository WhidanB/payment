"""Domain errors."""

from __future__ import annotations


class PaymentDomainError(Exception):
    """Base class for domain rule violations."""


class InvalidPaymentRequest(PaymentDomainError):
    """The payment request data breaks a domain invariant (bad amount, currency...)."""


class TransactionAlreadyResolved(PaymentDomainError):
    """Attempt to resolve a transaction that is no longer pending."""
