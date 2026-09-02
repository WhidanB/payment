"""Transaction — one attempt to settle a payment request.

Cadrage metier 3.4: "Tentative de paiement" (identifiant, paiement, date, resultat).
Each transaction is unique (UUID v7); several transactions may answer the same request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.model.clock import now
from app.domain.model.enums import TransactionStatus
from app.domain.model.errors import TransactionAlreadyResolved
from app.domain.model.ids import new_id


@dataclass
class Transaction:
    id: str
    payment_id: str
    attempt: int
    status: TransactionStatus = TransactionStatus.PENDING
    created_at: datetime = field(default_factory=now)
    resolved_at: datetime | None = None

    @classmethod
    def open(cls, payment_id: str, attempt: int) -> "Transaction":
        return cls(id=new_id(), payment_id=payment_id, attempt=attempt)

    @property
    def is_pending(self) -> bool:
        return self.status is TransactionStatus.PENDING

    def accept(self) -> None:
        self._resolve(TransactionStatus.ACCEPTED)

    def refuse(self) -> None:
        self._resolve(TransactionStatus.REFUSED)

    def _resolve(self, status: TransactionStatus) -> None:
        if not self.is_pending:
            raise TransactionAlreadyResolved(
                f"transaction {self.id} already {self.status.value}"
            )
        self.status = status
        self.resolved_at = now()
