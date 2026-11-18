"""HTTP DTOs (request/response) and mapping to/from the domain."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.domain.model.enums import PaymentStatus, ReferenceType, SourceService, TransactionStatus
from app.domain.model.payment import (
    MAX_AMOUNT_CENTS,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MAX_REFERENCE_ID_LENGTH,
    PaymentReference,
    PaymentRequest,
)
from app.domain.model.transaction import Transaction

IdempotencyKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
]
ReferenceId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REFERENCE_ID_LENGTH),
]
# strict: "1250", 12.5 and true are rejected instead of being silently coerced
AmountCents = Annotated[int, Field(strict=True, gt=0, le=MAX_AMOUNT_CENTS)]


class Reference(BaseModel):
    type: ReferenceType = Field(examples=["BOOKING"])
    id: ReferenceId = Field(
        examples=["resa_01J9Z3K2QeXAMPLE"], description="Booking id or parking stay id"
    )

    def to_domain(self) -> PaymentReference:
        return PaymentReference(type=self.type, id=self.id)

    @classmethod
    def from_domain(cls, reference: PaymentReference) -> "Reference":
        return cls(type=reference.type, id=reference.id)


class CreatePaymentRequest(BaseModel):
    idempotency_key: IdempotencyKey = Field(
        examples=["booking-4567-1"],
        description=(
            "Caller-supplied key, unique per business operation. Replaying it with the same "
            "payload is safe; reusing it with a different payload is a 409."
        ),
    )
    amount: AmountCents = Field(
        examples=[1250], description="Integer amount in minor units (cents), 1 to 10 000 000"
    )
    currency: Literal["EUR"] = Field(default="EUR", examples=["EUR"])
    reference: Reference
    source_service: SourceService = Field(examples=["booking"])


class TransactionResponse(BaseModel):
    transaction_id: str
    attempt: int
    status: TransactionStatus
    created_at: datetime
    resolved_at: datetime | None

    @classmethod
    def from_domain(cls, transaction: Transaction) -> "TransactionResponse":
        return cls(
            transaction_id=transaction.id,
            attempt=transaction.attempt,
            status=transaction.status,
            created_at=transaction.created_at,
            resolved_at=transaction.resolved_at,
        )


class PaymentResponse(BaseModel):
    payment_id: str
    idempotency_key: str
    status: PaymentStatus
    amount: int
    currency: str
    reference: Reference
    source_service: SourceService
    transactions: list[TransactionResponse]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, payment: PaymentRequest) -> "PaymentResponse":
        return cls(
            payment_id=payment.id,
            idempotency_key=payment.idempotency_key,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
            reference=Reference.from_domain(payment.reference),
            source_service=payment.source_service,
            transactions=[TransactionResponse.from_domain(t) for t in payment.transactions],
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )
