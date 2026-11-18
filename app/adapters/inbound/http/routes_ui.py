"""Operations / demo UI: a single static page served by the service itself."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(include_in_schema=False)

_INDEX = Path(__file__).parent / "ui" / "index.html"


@router.get("/ui")
def ui() -> FileResponse:
    return FileResponse(_INDEX, media_type="text/html")


@router.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")
