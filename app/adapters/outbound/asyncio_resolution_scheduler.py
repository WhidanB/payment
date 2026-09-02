"""asyncio implementation of :class:`ResolutionScheduler`.

Runs the resolution callback as a fire-and-forget task after a delay. Because the
work lives in the event loop, the service must run with a single worker.
"""

from __future__ import annotations

import asyncio
import logging

from app.domain.ports.resolution_scheduler import ResolutionCallback, ResolutionScheduler

logger = logging.getLogger("payment.scheduler")


class AsyncioResolutionScheduler(ResolutionScheduler):
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, delay_seconds: float, callback: ResolutionCallback) -> None:
        task = asyncio.create_task(self._run_after(delay_seconds, callback))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_after(self, delay_seconds: float, callback: ResolutionCallback) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            await callback()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a background task must not die silently
            logger.exception("scheduler.callback_failed")

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
