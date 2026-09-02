"""Single source of 'now' for the domain (UTC, timezone-aware)."""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(tz=timezone.utc)
