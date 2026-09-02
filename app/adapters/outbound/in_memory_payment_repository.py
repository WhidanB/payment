"""In-memory implementation of :class:`PaymentRepository`.

Good enough for the MVP. A SQL adapter can replace it without touching the domain.
Use a single worker: this store lives in the process.
"""

from __future__ import annotations

import copy

from app.domain.model.payment import PaymentRequest
from app.domain.ports.payment_repository import PaymentRepository


class InMemoryPaymentRepository(PaymentRepository):
    def __init__(self) -> None:
        self._by_id: dict[str, PaymentRequest] = {}
        self._id_by_key: dict[str, str] = {}

    async def save(self, payment: PaymentRequest) -> None:
        self._by_id[payment.id] = copy.deepcopy(payment)
        self._id_by_key[payment.idempotency_key] = payment.id

    async def get(self, payment_id: str) -> PaymentRequest | None:
        found = self._by_id.get(payment_id)
        return copy.deepcopy(found) if found is not None else None

    async def find_by_idempotency_key(self, idempotency_key: str) -> PaymentRequest | None:
        payment_id = self._id_by_key.get(idempotency_key)
        return await self.get(payment_id) if payment_id is not None else None
