"""PaymentRequest — the aggregate root.

Cadrage metier 3.4: "Paiement" (identifiant, montant, statut, dates) + "Cle d'idempotence"
(identifiant fourni par le demandeur, paiement associe).

A payment request is identified for idempotency by a caller-supplied key. It aggregates
1..N transactions (attempts). Its status is derived from those transactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.model.clock import now
from app.domain.model.enums import PaymentStatus, ReferenceType, SourceService
from app.domain.model.errors import InvalidPaymentRequest
from app.domain.model.ids import new_id
from app.domain.model.transaction import Transaction

_ALLOWED_CURRENCIES = {"EUR"}


@dataclass(frozen=True)
class PaymentReference:
    """What is being paid for (booking id or parking stay id)."""

    type: ReferenceType
    id: str


@dataclass
class PaymentRequest:
    id: str
    idempotency_key: str
    amount: int  # minor units (cents)
    currency: str
    reference: PaymentReference
    source_service: SourceService
    max_attempts: int
    status: PaymentStatus = PaymentStatus.PENDING
    transactions: list[Transaction] = field(default_factory=list)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        amount: int,
        currency: str,
        reference: PaymentReference,
        source_service: SourceService,
        max_attempts: int,
    ) -> "PaymentRequest":
        if not idempotency_key or not idempotency_key.strip():
            raise InvalidPaymentRequest("idempotency_key is required")
        if amount <= 0:
            raise InvalidPaymentRequest("amount must be a positive number of cents")
        if currency not in _ALLOWED_CURRENCIES:
            raise InvalidPaymentRequest(f"unsupported currency: {currency}")
        if max_attempts < 1:
            raise InvalidPaymentRequest("max_attempts must be >= 1")
        return cls(
            id=new_id(),
            idempotency_key=idempotency_key,
            amount=amount,
            currency=currency,
            reference=reference,
            source_service=source_service,
            max_attempts=max_attempts,
        )

    # -- transactions -----------------------------------------------------------

    @property
    def current_transaction(self) -> Transaction | None:
        return self.transactions[-1] if self.transactions else None

    def open_transaction(self) -> Transaction:
        """Start a new attempt for this request."""

        transaction = Transaction.open(payment_id=self.id, attempt=len(self.transactions) + 1)
        self.transactions.append(transaction)
        self._touch()
        return transaction

    def can_retry(self) -> bool:
        return len(self.transactions) < self.max_attempts

    # -- aggregate status -----------------------------------------------------------

    def mark_accepted(self) -> None:
        self.status = PaymentStatus.ACCEPTED
        self._touch()

    def mark_refused(self) -> None:
        self.status = PaymentStatus.REFUSED
        self._touch()

    @property
    def is_settled(self) -> bool:
        return self.status is not PaymentStatus.PENDING

    def _touch(self) -> None:
        self.updated_at = now()
