"""UUID v7 generation — the only place the domain touches the uuid library.

Python's stdlib gains ``uuid.uuid7()`` in 3.14; until then we rely on ``uuid-utils``.
"""

from __future__ import annotations

import uuid_utils


def new_id() -> str:
    """Return a fresh UUID v7 as a string (time-ordered identifier)."""

    return str(uuid_utils.uuid7())
