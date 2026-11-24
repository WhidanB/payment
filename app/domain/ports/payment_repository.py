"""Outbound port: persistence of payment requests."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.model.payment import PaymentRequest


class PaymentRepository(ABC):
    @abstractmethod
    async def save(self, payment: PaymentRequest) -> None:
        """Insert or update the aggregate (transactions included), atomically.

        Raises IdempotencyKeyTaken if a *different* request already owns the key.
        """

    @abstractmethod
    async def get(self, payment_id: str) -> PaymentRequest | None: ...

    @abstractmethod
    async def find_by_idempotency_key(self, idempotency_key: str) -> PaymentRequest | None: ...

    @abstractmethod
    async def list_recent(self, limit: int) -> list[PaymentRequest]:
        """Most recently created requests first."""

    @abstractmethod
    async def find_with_pending_transactions(self) -> list[PaymentRequest]:
        """Requests that still have a PENDING transaction (to resume after a restart)."""
