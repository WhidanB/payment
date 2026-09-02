"""Use-cases for the payment service.

Responsibilities:
- idempotent creation of a payment request (same key -> same request, no double charge);
- asynchronous resolution of a transaction after the PENDING delay;
- one automatic retry on refusal.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

from app.application.errors import PaymentNotFound
from app.domain.model.payment import PaymentReference, PaymentRequest
from app.domain.model.enums import SourceService
from app.domain.model.transaction import Transaction
from app.domain.ports.payment_gateway import PaymentGateway
from app.domain.ports.payment_repository import PaymentRepository
from app.domain.ports.resolution_scheduler import ResolutionScheduler

logger = logging.getLogger("payment.service")


@dataclass(frozen=True)
class RequestPaymentCommand:
    idempotency_key: str
    amount: int
    currency: str
    reference: PaymentReference
    source_service: SourceService


@dataclass(frozen=True)
class RequestPaymentResult:
    payment: PaymentRequest
    created: bool  # False when an existing request was returned (idempotent replay)


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepository,
        gateway: PaymentGateway,
        scheduler: ResolutionScheduler,
        *,
        pending_delay_seconds: float,
        max_attempts: int,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._scheduler = scheduler
        self._pending_delay_seconds = pending_delay_seconds
        self._max_attempts = max_attempts
        self._key_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # -- commands / queries ----------------------------------------------------

    async def request_payment(self, command: RequestPaymentCommand) -> RequestPaymentResult:
        async with self._key_locks[command.idempotency_key]:
            existing = await self._repository.find_by_idempotency_key(command.idempotency_key)
            if existing is not None:
                logger.info(
                    "payment.idempotent_hit",
                    extra=_fields(existing, transaction=existing.current_transaction),
                )
                return RequestPaymentResult(payment=existing, created=False)

            payment = PaymentRequest.create(
                idempotency_key=command.idempotency_key,
                amount=command.amount,
                currency=command.currency,
                reference=command.reference,
                source_service=command.source_service,
                max_attempts=self._max_attempts,
            )
            transaction = payment.open_transaction()
            await self._repository.save(payment)

        logger.info("payment.requested", extra=_fields(payment))
        logger.info("transaction.created", extra=_fields(payment, transaction=transaction))
        self._schedule_resolution(payment.id, transaction.id)
        return RequestPaymentResult(payment=payment, created=True)

    async def get_payment(self, payment_id: str) -> PaymentRequest:
        payment = await self._repository.get(payment_id)
        if payment is None:
            raise PaymentNotFound(payment_id)
        return payment

    # -- asynchronous resolution ---------------------------------------------------

    def _schedule_resolution(self, payment_id: str, transaction_id: str) -> None:
        async def _callback() -> None:
            await self._resolve_transaction(payment_id, transaction_id)

        self._scheduler.schedule(self._pending_delay_seconds, _callback)

    async def _resolve_transaction(self, payment_id: str, transaction_id: str) -> None:
        payment = await self._repository.get(payment_id)
        if payment is None:
            return
        transaction = payment.transaction_by_id(transaction_id)
        if transaction is None or not transaction.is_pending:
            return

        result = await self._gateway.authorize(
            amount=payment.amount,
            currency=payment.currency,
            reference=payment.reference,
        )

        if result.approved:
            transaction.accept()
            payment.mark_accepted()
            await self._repository.save(payment)
            logger.info("transaction.accepted", extra=_fields(payment, transaction=transaction))
            logger.info("payment.accepted", extra=_fields(payment))
            return

        transaction.refuse()
        logger.info(
            "transaction.refused",
            extra=_fields(payment, transaction=transaction, detail=result.detail),
        )

        if payment.can_retry():
            retry_transaction = payment.open_transaction()
            await self._repository.save(payment)
            logger.info(
                "payment.retry_scheduled",
                extra=_fields(payment, transaction=retry_transaction),
            )
            logger.info(
                "transaction.created", extra=_fields(payment, transaction=retry_transaction)
            )
            self._schedule_resolution(payment.id, retry_transaction.id)
        else:
            payment.mark_refused()
            await self._repository.save(payment)
            logger.info("payment.refused", extra=_fields(payment))


def _fields(
    payment: PaymentRequest,
    *,
    transaction: Transaction | None = None,
    detail: str | None = None,
) -> dict:
    data = {
        "payment_id": payment.id,
        "idempotency_key": payment.idempotency_key,
        "payment_status": payment.status.value,
        "amount": payment.amount,
        "currency": payment.currency,
        "reference_type": payment.reference.type.value,
        "reference_id": payment.reference.id,
        "source_service": payment.source_service.value,
        "attempts": len(payment.transactions),
    }
    if transaction is not None:
        data["transaction_id"] = transaction.id
        data["transaction_status"] = transaction.status.value
        data["attempt"] = transaction.attempt
    if detail is not None:
        data["detail"] = detail
    return data
