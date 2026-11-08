"""Optional Bearer API-token authentication."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that never require a token (even when api_tokens is set).
PUBLIC_PATHS = frozenset({"/health"})


def token_is_allowed(provided: str, allowed: Sequence[str]) -> bool:
    """Return True if *provided* matches any configured token (timing-safe)."""
    if not provided or not allowed:
        return False
    matched = False
    for token in allowed:
        if len(provided) == len(token) and secrets.compare_digest(provided, token):
            matched = True
    return matched


def extract_bearer_token(authorization: str | None) -> str | None:
    """Parse `Authorization: Bearer <token>`; return None if missing/malformed."""
    if not authorization:
        return None
    scheme, _, remainder = authorization.partition(" ")
    if scheme.lower() != "bearer" or not remainder.strip():
        return None
    return remainder.strip()


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer …` when api_tokens is non-empty."""

    def __init__(self, app, tokens: Sequence[str]) -> None:
        super().__init__(app)
        self._tokens = list(tokens)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._tokens:
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        # /health is public; keep trailing-slash variants covered.
        if path in PUBLIC_PATHS or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        provided = extract_bearer_token(request.headers.get("Authorization"))
        if provided is None or not token_is_allowed(provided, self._tokens):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "error": "Unauthorized — send Authorization: Bearer <token>",
                        "code": "unauthorized",
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)
