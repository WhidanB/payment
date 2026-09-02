"""Outbound port: deferred execution of the transaction resolution.

Abstracts "resolve this transaction in 15 seconds" away from asyncio so the domain
stays framework-free and tests can resolve immediately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

ResolutionCallback = Callable[[], Awaitable[None]]


class ResolutionScheduler(ABC):
    @abstractmethod
    def schedule(self, delay_seconds: float, callback: ResolutionCallback) -> None:
        """Run ``callback`` once, ``delay_seconds`` from now."""
