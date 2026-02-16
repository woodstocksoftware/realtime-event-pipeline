"""Security middleware and authentication helpers."""

import logging
from collections import defaultdict
from typing import Optional

from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.config import API_KEY, MAX_WS_CONNECTIONS_PER_IP, REQUIRE_AUTH

logger = logging.getLogger(__name__)

# ── Security Headers ────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


# ── API Key Authentication ──────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_api_key(api_key: Optional[str]) -> None:
    """Validate API key if auth is required."""
    if not REQUIRE_AUTH:
        return
    if not api_key or api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_auth(api_key: Optional[str] = Depends(_api_key_header)) -> None:
    """Dependency that enforces authentication on protected endpoints."""
    _check_api_key(api_key)


async def require_admin(api_key: Optional[str] = Depends(_api_key_header)) -> None:
    """Dependency that enforces admin authentication (same key, separate for RBAC extension)."""
    _check_api_key(api_key)


def verify_ws_api_key(websocket: WebSocket) -> None:
    """Validate API key from WebSocket query params or headers."""
    if not REQUIRE_AUTH:
        return
    key = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
    if not key or key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── WebSocket Connection Limiter ────────────────────────────────


class WebSocketConnectionLimiter:
    """Track and limit WebSocket connections per IP."""

    def __init__(self, max_per_ip: int = MAX_WS_CONNECTIONS_PER_IP):
        self.max_per_ip = max_per_ip
        self._connections: dict[str, int] = defaultdict(int)

    def try_connect(self, client_ip: str) -> bool:
        if self._connections[client_ip] >= self.max_per_ip:
            logger.warning("WS connection limit reached for IP %s", client_ip)
            return False
        self._connections[client_ip] += 1
        return True

    def disconnect(self, client_ip: str) -> None:
        self._connections[client_ip] = max(0, self._connections[client_ip] - 1)
        if self._connections[client_ip] == 0:
            del self._connections[client_ip]


ws_limiter = WebSocketConnectionLimiter()
