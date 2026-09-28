"""
A mock third-party API for exercising ResilientAPIClient over real HTTP.

Unlike respx, which fakes the HTTP layer inside the process, this runs
a real server on a real socket. That surfaces the failures a mock at
the transport layer cannot: read timeouts, refused connections, and
header handling on the wire.

Every scenario endpoint is deterministic. Stateful endpoints take a
`key` query parameter, so each test gets its own independent counter.

Scenarios:

  GET  /v1/ok                      always 200
  GET  /v1/flaky                   fails the first `fail_first` calls with
                                   `status` (default 503), then succeeds
  GET  /v1/ratelimited             fails the first `fail_first` calls with
                                   429 and a Retry-After of `retry_after`
  GET  /v1/always-down             always 503
  GET  /v1/missing                 always 404
  GET  /v1/slow                    responds after `delay` seconds
  POST /oauth/token                OAuth2 client credentials grant
  GET  /v1/secure                  requires a valid bearer token
  POST /v1/payments                applies its side effect BEFORE possibly
                                   failing or stalling, like a response lost
                                   in transit. Honors an Idempotency-Key
                                   header: a repeated key is replayed, not
                                   applied again.

Run it standalone for manual poking:

    python integrations/resilient_client/mock_partner_server.py
"""

import asyncio
import threading
import time
import uuid
from collections import defaultdict
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

VALID_CLIENT_ID = "test-client"
VALID_CLIENT_SECRET = "test-secret"


class MockState:
    """Thread-safe counters the tests read to see what the server observed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.token_ttl_s = 300
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.hits: dict[str, int] = defaultdict(int)
            self.calls: dict[str, int] = defaultdict(int)
            self.valid_tokens: set[str] = set()
            self.tokens_issued = 0
            self.payments_applied = 0
            self.idempotent_results: dict[str, int] = {}

    def record_hit(self, path: str) -> None:
        with self._lock:
            self.hits[path] += 1

    def next_call(self, key: str) -> int:
        """Return how many times this scenario key has been called, including now."""
        with self._lock:
            self.calls[key] += 1
            return self.calls[key]

    def issue_token(self) -> str:
        with self._lock:
            self.tokens_issued += 1
            token = f"token-{uuid.uuid4().hex}"
            self.valid_tokens.add(token)
            return token

    def apply_payment(self, idempotency_key: str | None = None) -> tuple[int, bool]:
        """
        Apply a payment. Returns (payment_id, replayed). A repeated
        idempotency key returns the original result without applying
        the side effect again.
        """
        with self._lock:
            if idempotency_key is not None and idempotency_key in self.idempotent_results:
                return self.idempotent_results[idempotency_key], True
            self.payments_applied += 1
            if idempotency_key is not None:
                self.idempotent_results[idempotency_key] = self.payments_applied
            return self.payments_applied, False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "hits": dict(self.hits),
                "tokens_issued": self.tokens_issued,
                "payments_applied": self.payments_applied,
            }


def create_app() -> tuple[FastAPI, MockState]:
    app = FastAPI(title="Mock partner API")
    state = MockState()

    @app.middleware("http")
    async def count_hits(request: Request, call_next):
        state.record_hit(request.url.path)
        return await call_next(request)

    @app.get("/v1/ok")
    def ok():
        return {"ok": True}

    @app.get("/v1/flaky")
    def flaky(key: str = "default", fail_first: int = 0, status: int = 503):
        call_number = state.next_call(f"flaky:{key}")
        if call_number <= fail_first:
            return JSONResponse({"error": "transient"}, status_code=status)
        return {"ok": True, "call_number": call_number}

    @app.get("/v1/ratelimited")
    def ratelimited(key: str = "default", fail_first: int = 1, retry_after: str = "1"):
        call_number = state.next_call(f"ratelimited:{key}")
        if call_number <= fail_first:
            return JSONResponse(
                {"error": "slow down"},
                status_code=429,
                headers={"Retry-After": retry_after},
            )
        return {"ok": True, "call_number": call_number}

    @app.get("/v1/always-down")
    def always_down():
        return JSONResponse({"error": "down"}, status_code=503)

    @app.get("/v1/missing")
    def missing():
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/v1/slow")
    async def slow(delay: float = 1.0):
        await asyncio.sleep(delay)
        return {"ok": True, "delay": delay}

    @app.post("/oauth/token")
    async def token(request: Request):
        body = parse_qs((await request.body()).decode())
        client_id = body.get("client_id", [""])[0]
        client_secret = body.get("client_secret", [""])[0]
        grant_type = body.get("grant_type", [""])[0]
        if (
            grant_type != "client_credentials"
            or client_id != VALID_CLIENT_ID
            or client_secret != VALID_CLIENT_SECRET
        ):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        return {
            "access_token": state.issue_token(),
            "token_type": "Bearer",
            "expires_in": state.token_ttl_s,
        }

    @app.get("/v1/secure")
    def secure(request: Request):
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip()
        if token not in state.valid_tokens:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return {"secure": True}

    @app.post("/v1/payments")
    def payments(request: Request, key: str = "default", fail_first: int = 0, delay: float = 0):
        # The side effect happens first, then the response may "get lost"
        # (a 503, or a stall long enough to hit the client's read timeout).
        # This is what makes a retried POST dangerous in real systems.
        payment_id, replayed = state.apply_payment(request.headers.get("idempotency-key"))
        call_number = state.next_call(f"payments:{key}")
        if delay:
            time.sleep(delay)
        if call_number <= fail_first:
            return JSONResponse({"error": "gateway timeout"}, status_code=503)
        return {"payment_id": payment_id, "replayed": replayed}

    # Handy when running standalone.
    @app.get("/_stats")
    def stats():
        return state.snapshot()

    @app.post("/_reset")
    def reset():
        state.reset()
        return {"reset": True}

    return app, state


if __name__ == "__main__":
    import uvicorn

    mock_app, _ = create_app()
    uvicorn.run(mock_app, host="127.0.0.1", port=8099, log_level="info")
