"""Shared-secret auth for inbound calls (convention agreed with booking/access/...).

Every service protects its own routes with an `X-API-Key` header, except `/health`.
One key per service; callers get it privately (never in git). If no key is configured
server-side, the check is skipped — keeps local dev and tests working unchanged, and
lets a key be rolled out without breaking existing callers until it's set.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.container import Container

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(request: Request, provided_key: str | None = Security(_api_key_header)) -> None:
    container: Container = request.app.state.container
    expected = container.settings.api_key
    if not expected:
        return
    if provided_key is None or not hmac.compare_digest(
        provided_key.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-API-Key",
        )
