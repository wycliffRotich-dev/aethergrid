"""
The anonymous rate limit of the public app (ADR 0103, decisions 5 to 7).

A pure ASGI middleware, the outermost one, so every request is counted:
known routes, unknown paths, refused methods and CORS preflights, which the
CORS middleware would otherwise answer before anything behind it ran. A
refusal is a fixed 429 that names no client and no limit. It sets
Access-Control-Allow-Origin itself, only when the Origin header equals the
configured origin, so the browser can read the 429 and not a CORS error.
It never allows credentials.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.application.public_rate_limiter import (
    AnonymousRateLimiter,
    AnonymousRateLimitExceededError,
)
from app.presentation.public.client_address import select_client_address

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_BODY = b'{"detail":"Too many requests."}'
_WEBSOCKET_TRY_AGAIN_LATER = 1013


class AnonymousRateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: AnonymousRateLimiter,
        trusted_proxy_hops: int,
        allowed_origin: str,
    ) -> None:
        self._app = app
        self._limiter = limiter
        self._trusted_proxy_hops = trusted_proxy_hops
        self._allowed_origin = allowed_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]

        # Lifespan events are not requests.
        if kind not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        try:
            self._limiter.check(self._counted_address(scope))
        except AnonymousRateLimitExceededError as refusal:
            if kind == "websocket":
                await receive()
                await send(
                    {
                        "type": "websocket.close",
                        "code": _WEBSOCKET_TRY_AGAIN_LATER,
                    }
                )
            else:
                await self._refuse(scope, send, refusal.retry_after_seconds)
            return

        await self._app(scope, receive, send)

    def _counted_address(self, scope: Scope) -> str | None:
        client = scope.get("client")
        socket_address = client[0] if client else None
        lines = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name == b"x-forwarded-for"
        ]

        return select_client_address(
            socket_address, lines, self._trusted_proxy_hops
        )

    async def _refuse(
        self, scope: Scope, send: Send, retry_after_seconds: int
    ) -> None:
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_BODY)).encode("ascii")),
            (b"retry-after", str(retry_after_seconds).encode("ascii")),
        ]
        origin = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name == b"origin"
            ),
            None,
        )

        if origin is not None and origin.decode("latin-1") == self._allowed_origin:
            headers.append((b"access-control-allow-origin", origin))
            headers.append((b"vary", b"Origin"))

        await send(
            {"type": "http.response.start", "status": 429, "headers": headers}
        )
        await send({"type": "http.response.body", "body": _BODY})
