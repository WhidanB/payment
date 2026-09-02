"""Fake payment provider: approves everything except a configurable share of calls.

Lets us exercise the refusal + retry path without a real PSP (Stripe comes later).
"""

from __future__ import annotations

import logging
import random

from app.domain.model.payment import PaymentReference
from app.domain.ports.payment_gateway import GatewayResult, PaymentGateway

logger = logging.getLogger("payment.gateway")


class SimulatedPaymentGateway(PaymentGateway):
    def __init__(self, failure_rate: float = 0.05, rng: random.Random | None = None) -> None:
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0 and 1")
        self._failure_rate = failure_rate
        self._rng = rng or random.Random()

    async def authorize(
        self,
        *,
        amount: int,
        currency: str,
        reference: PaymentReference,
    ) -> GatewayResult:
        approved = self._rng.random() >= self._failure_rate
        detail = None if approved else "simulated_refusal"
        logger.info(
            "gateway.authorize",
            extra={
                "approved": approved,
                "amount": amount,
                "currency": currency,
                "reference_type": reference.type.value,
                "reference_id": reference.id,
                "detail": detail,
            },
        )
        return GatewayResult(approved=approved, detail=detail)
