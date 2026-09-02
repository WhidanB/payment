"""Test doubles and fixtures.

The gateway outcome is forced (no randomness) and resolution is drained manually so
the async flow is fully deterministic — no sleeps.
"""

from __future__ import annotations

from collections import deque

import pytest

from app.adapters.outbound.in_memory_payment_repository import InMemoryPaymentRepository
from app.application.payment_service import PaymentService, RequestPaymentCommand
from app.domain.model.enums import ReferenceType, SourceService
from app.domain.model.payment import PaymentReference
from app.domain.ports.payment_gateway import GatewayResult, PaymentGateway
from app.domain.ports.resolution_scheduler import ResolutionCallback, ResolutionScheduler


class ScriptedGateway(PaymentGateway):
    """Returns approvals from a script; defaults to `default` once the script is spent."""

    def __init__(self, outcomes: list[bool] | None = None, default: bool = True) -> None:
        self._outcomes = deque(outcomes or [])
        self._default = default
        self.calls = 0

    async def authorize(self, *, amount, currency, reference) -> GatewayResult:
        self.calls += 1
        approved = self._outcomes.popleft() if self._outcomes else self._default
        return GatewayResult(approved=approved, detail=None if approved else "forced_refusal")


class ManualScheduler(ResolutionScheduler):
    """Collects scheduled callbacks; `run_all()` drains them (retries included)."""

    def __init__(self) -> None:
        self._pending: deque[ResolutionCallback] = deque()

    def schedule(self, delay_seconds: float, callback: ResolutionCallback) -> None:
        self._pending.append(callback)

    async def run_all(self) -> None:
        while self._pending:
            await self._pending.popleft()()


@pytest.fixture
def repository() -> InMemoryPaymentRepository:
    return InMemoryPaymentRepository()


@pytest.fixture
def scheduler() -> ManualScheduler:
    return ManualScheduler()


@pytest.fixture
def make_service(repository, scheduler):
    def _make(gateway: PaymentGateway, *, max_attempts: int = 2) -> PaymentService:
        return PaymentService(
            repository,
            gateway,
            scheduler,
            pending_delay_seconds=0.0,
            max_attempts=max_attempts,
        )

    return _make


@pytest.fixture
def command() -> RequestPaymentCommand:
    return RequestPaymentCommand(
        idempotency_key="booking-1",
        amount=1250,
        currency="EUR",
        reference=PaymentReference(type=ReferenceType.BOOKING, id="resa_1"),
        source_service=SourceService.BOOKING,
    )
