"""Application-layer errors."""

from __future__ import annotations


class PaymentNotFound(Exception):
    def __init__(self, payment_id: str) -> None:
        super().__init__(f"payment {payment_id} not found")
        self.payment_id = payment_id
