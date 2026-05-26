"""Origin guard for unsafe browser requests."""

from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.auth.config import allowed_origins

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def reject_unexpected_unsafe_origin(request: Request, call_next) -> Response:
    if request.method.upper() in SAFE_METHODS:
        return await call_next(request)

    origin = request.headers.get("origin")
    if not origin:
        return await call_next(request)

    normalized = origin.strip().rstrip("/")
    if normalized == "null" or normalized not in allowed_origins():
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": "FORBIDDEN_ORIGIN",
                    "message": "Unsafe request origin is not allowed",
                }
            },
        )
    return await call_next(request)
