# resilient_client

A synchronous HTTP client for talking to third parties you do not
control and cannot fully see into: slow, rate limited, or occasionally
down. It adds retry with backoff, a circuit breaker, precise error
types, and config validation on top of `httpx`.

Background: [ADR 0047](../../docs/adr/0047-resilient-gov-api-client.md)
explains why it was built, and
[ADR 0048](../../docs/adr/0048-generalize-gov-client-to-resilient-api-client.md)
explains why it is named and located as a general purpose client.

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

`get`, `post`, `put`, and `delete` return the parsed JSON body, or
`None` if the response body is empty. Extra keyword arguments such as
`json=`, `params=`, and `headers=` pass straight through to `httpx`.

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
| `ServerError` | 5xx persisted through every attempt. Carries `status_code`. | Yes | Yes |
| `RetryExhaustedError` | Transport failure (timeout, refused connection, DNS) through every attempt. No response existed. | Yes | Yes |
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

- **It retries every HTTP method, including POST.** If a request
  reaches the server but the response is lost, a retried POST can
  perform its side effect twice. For non idempotent writes, send an
  idempotency key if the partner supports one, or lower
  `max_attempts` to 1 for those calls.
- **It is synchronous.** It uses blocking `httpx.Client` and
  `time.sleep`. Calling it directly inside an `async def` FastAPI
  route will block the event loop during retries. Use a plain `def`
  route, or run it in a thread pool.
- **The breaker is per process and not shared.** Multiple workers each
  track failures independently.

## Testing your integration

Inject a mocked transport, or use `respx`, so tests need no network
and no real credentials. The suite in
`test_resilient_api_client.py` is a working reference for mocking
success, retries, rate limiting, and each breaker state.

```
python -m pytest integrations/resilient_client/ -v
```
