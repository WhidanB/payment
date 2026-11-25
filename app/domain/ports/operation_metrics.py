"""Outbound port: counting business operations for monitoring.

Prometheus today; the application only says what happened, never how it is exported.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

Operation = Literal["payment", "transaction"]
Outcome = Literal["requested", "replayed", "conflict", "retried", "accepted", "refused"]


class OperationMetrics(ABC):
    @abstractmethod
    def record(self, operation: Operation, outcome: Outcome) -> None:
        """Count one occurrence of ``operation`` ending with ``outcome``."""


class NoOperationMetrics(OperationMetrics):
    """Default when nothing is monitored (unit tests, scripts)."""

    def record(self, operation: Operation, outcome: Outcome) -> None:
        pass
