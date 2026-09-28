# resilient_client

A synchronous HTTP client for talking to third parties you do not
control and cannot fully see into: slow, rate limited, or occasionally
down. It adds retry with backoff, a circuit breaker, precise error
types, and config validation on top of `httpx`.

Background: [ADR 0047](../../docs/adr/0047-resilient-gov-api-client.md)
explains why it was built, and
[ADR 0048](../../docs/adr/0048-generalize-gov-client-to-resilient-api-client.md)
explains why it is named and located as a general purpose client, and
[ADR 0049](../../docs/adr/0049-resilient-client-replays-only-safe-requests.md)
explains why it only retries requests that are safe to replay.

## Quick start

```python
from integrations.resilient_client.resilient_api_client import (
    ResilientAPIClient,
    ResilientClientConfig,
)

config = ResilientClientConfig(base_url="https://api.partner.example")

with ResilientAPIClient(config) as client:
    data = client.get("/v1/status")
```

Run from the repo root. There is no `__init__.py`, so `integrations`
works as a namespace package only when the root is on the import path.

`get`, `post`, `put`, `patch`, and `delete` return the parsed JSON
body, or `None` if the response body is empty. Extra keyword arguments
such as `json=`, `params=`, and `headers=` pass straight through to
`httpx`. Every call also accepts `idempotency_key=`, covered under
Retry safety below.

## Adding auth

Both mechanisms are optional and can be combined.

```python
from integrations.resilient_client.resilient_api_client import (
    MTLSConfig,
    OAuth2Config,
    ResilientClientConfig,
)

config = ResilientClientConfig(
    base_url="https://api.partner.example",
    mtls=MTLSConfig(
        cert_path="/etc/certs/client.crt",
        key_path="/etc/certs/client.key",
        ca_bundle_path="/etc/certs/partner-ca.pem",  # optional
    ),
    oauth2=OAuth2Config(
        token_url="https://api.partner.example/oauth/token",
        client_id=os.environ["PARTNER_CLIENT_ID"],
        client_secret=os.environ["PARTNER_CLIENT_SECRET"],
    ),
)
```

OAuth2 tokens are fetched on first use, cached, and refreshed shortly
before they expire. Load secrets from the environment or a secrets
manager. Never hardcode them or commit them.

## Handling errors

Every error inherits from `ResilientAPIError`, and each type means a
different thing, so catch them separately.

| Exception | Meaning | Retried? | Counts toward breaker? |
| --- | --- | --- | --- |
| `ClientError` | Non retryable 4xx such as 400 or 404. Carries `status_code` and `response_body`. | No | No |
| `RateLimitError` | 429 persisted through every attempt. Carries `retry_after_s`. | Yes | Yes |
| `ServerError` | 5xx that ended the request. Carries `status_code` and `outcome_unknown`. | Only if safe to replay | Yes |
| `RetryExhaustedError` | Transport failure (timeout, refused connection, DNS) that ended the request. No response existed. Carries `outcome_unknown`. | Only if safe to replay | Yes |
| `CircuitOpenError` | Breaker is open, so the call failed fast without touching the network. | n/a | n/a |
| `AuthError` | OAuth2 token could not be acquired. | No | No |
| `ConfigError` | Invalid config, raised at construction. | n/a | n/a |

```python
try:
    data = client.get("/v1/records/42")
except ClientError as exc:
    # Our mistake. Retrying will not help.
    log.error("bad request: %s %s", exc.status_code, exc.response_body)
except RateLimitError as exc:
    # Back off at a higher level, for example requeue the work.
    requeue(delay=exc.retry_after_s or 60)
except (ServerError, RetryExhaustedError, CircuitOpenError):
    # Their side is unhealthy. Degrade gracefully.
    return cached_or_default()
```

## Retry safety

Retrying is only safe when it cannot repeat a side effect. If a server
processes a request but the response is lost, replaying a POST can
charge a card twice while the caller sees a clean success. So the
client decides per request:

| Situation | Retried? | Why |
| --- | --- | --- |
| GET, HEAD, OPTIONS, PUT, DELETE, any transient failure | Yes | Idempotent by definition, replaying changes nothing. |
| Any method, request never left (refused connection, connect timeout) | Yes | The server cannot have acted on it. |
| Any method, 429 | Yes | The server declined it before acting. |
| POST or PATCH, 5xx or read timeout, no key | No | It may have been processed. A replay could repeat it. |
| POST or PATCH with `idempotency_key` | Yes | The partner can deduplicate the replay. |

When a failure leaves it genuinely unknown whether the request took
effect, `outcome_unknown` is `True` on `ServerError` and
`RetryExhaustedError`. Reconcile with the partner instead of sending it
again blindly.

```python
try:
    client.post("/v1/payments", json=payload, idempotency_key=f"order-{order.id}")
except (ServerError, RetryExhaustedError) as exc:
    if exc.outcome_unknown:
        # It may have gone through. Look it up before trying again.
        reconcile(order)
    else:
        raise
```

Only pass `idempotency_key` when the partner honors it. Sending a key
to a server that ignores it does not make a replay safe.

Two knobs for partners with different rules:

- `ResilientClientConfig(idempotency_header="X-Request-Id")` changes
  the header the key is sent in. The default is `Idempotency-Key`.
- `RetryConfig(retryable_methods=("GET", "POST"))` marks methods as safe
  to replay for a partner known to deduplicate everything.

## Tuning

Defaults are conservative placeholders. Tune them per partner once you
know their real rate limits and behavior.

```python
from integrations.resilient_client.resilient_api_client import (
    CircuitBreaker,
    ResilientClientConfig,
    RetryConfig,
)

config = ResilientClientConfig(
    base_url="https://api.partner.example",
    timeout_s=10.0,
    retry=RetryConfig(
        max_attempts=4,          # total tries, including the first
        base_delay_s=0.5,        # first backoff, doubles each attempt
        max_delay_s=8.0,         # backoff ceiling
        jitter_s=0.25,           # random extra delay, avoids lockstep
        max_retry_after_s=60.0,  # cap on honoring a Retry-After header
    ),
    circuit_breaker=CircuitBreaker(
        failure_threshold=5,     # consecutive failed requests to trip
        reset_timeout_s=30.0,    # wait before allowing one trial call
    ),
)
```

When a response carries a `Retry-After` header, the client waits that
long (clamped to `max_retry_after_s`) instead of its own backoff.

## Rules of thumb

- **One client per third party.** The circuit breaker lives on the
  config, so each partner needs its own config and client. Sharing one
  would let one flaky partner trip the breaker for all the others.
- **Keep the client for the life of the process.** Reusing it keeps
  the connection pool, the cached OAuth2 token, and the breaker state.
  Building one per request throws all three away.
- **Use `with` or call `close()`** when you do own the lifecycle.
- **`http://` base URLs are rejected** unless the host is `localhost`
  or `127.0.0.1`, which keeps local mock servers usable.

## Known limitations

Read these before wiring it into anything important.

- **It is synchronous.** It uses blocking `httpx.Client` and
  `time.sleep`. Calling it directly inside an `async def` FastAPI
  route will block the event loop during retries. Use a plain `def`
  route, or run it in a thread pool.
- **The breaker is per process and not shared.** Multiple workers each
  track failures independently.

## Testing your integration

There are two layers of tests, and neither needs real credentials.

- `test_resilient_api_client.py` mocks the HTTP layer with `respx`. It
  is fast and precise, and a working reference for mocking success,
  retries, rate limiting, retry safety, and each breaker state.
- `test_resilient_client_e2e.py` runs the real client against
  `mock_partner_server.py` over real HTTP on localhost. It covers what
  a transport mock cannot: real read timeouts, refused connections,
  and header handling on the wire.

To poke the mock partner by hand, run it standalone on port 8099:

```
python integrations/resilient_client/mock_partner_server.py
```

```
python -m pytest integrations/resilient_client/ -v
```
