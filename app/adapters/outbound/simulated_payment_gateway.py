"""Fake payment provider: approves everything except a configurable share of calls.

Lets us exercise the refusal + retry path without a real PSP (Stripe comes later).

Like Stripe's test cards, some reference ids force a deterministic outcome so the
refusal path can be demonstrated on demand:

- ``demo-refuse-once...``   refused on attempt 1, accepted on the automatic retry;
- ``demo-refuse-always...`` refused on every attempt (the request ends REFUSED).
"""

from __future__ import annotations

import logging
import random

from app.domain.model.payment import PaymentReference
from app.domain.ports.payment_gateway import GatewayResult, PaymentGateway

logger = logging.getLogger("payment.gateway")

REFUSE_ONCE_PREFIX = "demo-refuse-once"
REFUSE_ALWAYS_PREFIX = "demo-refuse-always"


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
        transaction_id: str,
        attempt: int,
    ) -> GatewayResult:
        scenario, approved = self._decide(reference.id, attempt)
        detail = None if approved else "simulated_refusal"
        logger.info(
            "gateway.authorize",
            extra={
                "approved": approved,
                "scenario": scenario,
                "amount": amount,
                "currency": currency,
                "reference_type": reference.type.value,
                "reference_id": reference.id,
                "transaction_id": transaction_id,
                "attempt": attempt,
                "detail": detail,
            },
        )
        return GatewayResult(approved=approved, detail=detail)

    def _decide(self, reference_id: str, attempt: int) -> tuple[str, bool]:
        if reference_id.startswith(REFUSE_ALWAYS_PREFIX):
            return "refuse_always", False
        if reference_id.startswith(REFUSE_ONCE_PREFIX):
            return "refuse_once", attempt > 1
        return "random", self._rng.random() >= self._failure_rate
