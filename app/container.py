"""Composition root — the single place where adapters are wired to the domain.

Swap an adapter here (e.g. Stripe gateway, SQL repository) without touching
``app/domain`` or ``app/application``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.outbound.asyncio_resolution_scheduler import AsyncioResolutionScheduler
from app.adapters.outbound.in_memory_payment_repository import InMemoryPaymentRepository
from app.adapters.outbound.postgres_payment_repository import PostgresPaymentRepository
from app.adapters.outbound.simulated_payment_gateway import SimulatedPaymentGateway
from app.application.payment_service import PaymentService
from app.config import Settings, get_settings
from app.domain.ports.payment_gateway import PaymentGateway
from app.domain.ports.payment_repository import PaymentRepository
from app.domain.ports.resolution_scheduler import ResolutionScheduler


@dataclass
class Container:
    settings: Settings
    repository: PaymentRepository
    gateway: PaymentGateway
    scheduler: ResolutionScheduler
    payment_service: PaymentService

    @property
    def storage(self) -> str:
        return "postgres" if isinstance(self.repository, PostgresPaymentRepository) else "memory"

    async def close(self) -> None:
        if isinstance(self.scheduler, AsyncioResolutionScheduler):
            await self.scheduler.shutdown()
        if isinstance(self.repository, PostgresPaymentRepository):
            await self.repository.close()


async def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()

    repository: PaymentRepository
    if settings.database_url:
        repository = await PostgresPaymentRepository.connect(settings.database_url)
    else:
        repository = InMemoryPaymentRepository()
    gateway: PaymentGateway = SimulatedPaymentGateway(failure_rate=settings.failure_rate)
    scheduler: ResolutionScheduler = AsyncioResolutionScheduler()

    payment_service = PaymentService(
        repository,
        gateway,
        scheduler,
        pending_delay_seconds=settings.pending_delay_seconds,
        max_attempts=settings.max_attempts,
    )

    return Container(
        settings=settings,
        repository=repository,
        gateway=gateway,
        scheduler=scheduler,
        payment_service=payment_service,
    )
