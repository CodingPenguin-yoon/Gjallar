"""Origin guard for unsafe browser requests."""

from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.auth.config import allowed_origins, allow_same_origin

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_same_origin(connection, origin: str | None) -> bool:
    if not allow_same_origin() or not origin or origin == "null":
        return False
    # Use the actual HTTP/WebSocket authority, never Origin or forwarded headers
    # to construct a trusted destination. WebSocket origins use HTTP(S) schemes.
    url = connection.url
    scheme = {"ws": "http", "wss": "https"}.get(url.scheme, url.scheme)
    return origin == f"{scheme}://{url.netloc}"


async def reject_unexpected_unsafe_origin(request: Request, call_next) -> Response:
    if request.method.upper() in SAFE_METHODS:
        return await call_next(request)

    origin = request.headers.get("origin")
    if not origin:
        return await call_next(request)

    normalized = origin.strip().rstrip("/")
    if normalized == "null" or (normalized not in allowed_origins() and not is_same_origin(request, normalized)):
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
