"""Outbound port: the actual payment provider.

Simulated today, Stripe tomorrow — only the adapter wired in the container changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.model.payment import PaymentReference


@dataclass(frozen=True)
class GatewayResult:
    approved: bool
    detail: str | None = None


class PaymentGateway(ABC):
    @abstractmethod
    async def authorize(
        self,
        *,
        amount: int,
        currency: str,
        reference: PaymentReference,
    ) -> GatewayResult:
        """Attempt to capture the amount. Never raises for a business refusal."""
