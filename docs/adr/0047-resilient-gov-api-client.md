# 0047. Resilient Client Architecture for Government API Integration

## Status

Accepted

## Context

AetherGrid is expected to integrate with a government-operated API as part of
an upcoming pilot. At the time of this decision, the following are not yet
known:

- The exact endpoint URLs (sandbox vs production)
- Whether authentication will be mTLS, OAuth2 client-credentials, or both
- Rate limits, timeout behavior, and maintenance windows on their side
- The reliability characteristics of their infrastructure under load

Government and other regulated third-party APIs are commonly slower to
support, less transparent about downtime, and stricter about security
posture than typical commercial SaaS APIs. We need an integration layer
that can be built and fully tested before real credentials exist, and
that behaves predictably when the remote side is degraded rather than
fully available.

## Decision

We will implement a dedicated `GovAPIClient` (in
`integrations/gov_client/`) with the following architectural properties:

1. Auth-agnostic by design. The client supports mTLS (client cert/key),
   OAuth2 client-credentials, or both simultaneously, since we do not
   yet know which the pilot will require. Auth config is injected via
   `GovAPIClientConfig`, not hardcoded.

2. Retry with exponential backoff and jitter. Transient failures
   (configurable status codes, default 429/500/502/503/504, plus
   transport-level errors) are retried up to a configurable attempt
   count. Non-retryable client errors (e.g. 404, 400) fail fast on the
   first attempt.

3. Circuit breaker, independent of retry. A `CircuitBreaker` (closed,
   open, half-open) trips after N consecutive request failures (not
   per low-level attempt) and fails fast for a cooldown period before
   allowing a single trial call through. This prevents the client from
   hammering a degraded government endpoint and keeps failure latency
   bounded and predictable.

4. Structured logging at every state transition. Request attempts,
   retries, and circuit breaker state changes are all logged, so
   behavior against a real, opaque, low-visibility government endpoint
   is debuggable after the fact.

5. Testability via dependency injection. The underlying `httpx.Client`
   accepts an injectable transport, allowing the full retry, circuit
   breaker, and auth logic to be exercised in tests via respx mocking,
   with no real network access or real credentials required. Test
   suite: `integrations/gov_client/test_gov_api_client.py` (7 tests,
   covering success, retry-then-recover, retry exhaustion,
   non-retryable errors, circuit breaker trip/half-open/recovery, and
   OAuth2 token acquisition and caching).

## Consequences

Positive:

- The integration can be built, reviewed, and fully tested before the
  pilot provides real sandbox access, de-risking the timeline.
- Failure behavior against a real degraded endpoint is bounded and
  observable rather than open-ended retries or silent hangs.
- Swapping in real credentials and endpoints later is a configuration
  change (`GovAPIClientConfig`), not a code change.

Negative and follow-ups:

- Default retryable_statuses treats all of 429/500/502/503/504 as
  transient. This should be revisited once we see the pilot's actual
  error semantics (for example, some 429s may carry a Retry-After
  header we are not yet honoring).
- Circuit breaker thresholds (failure_threshold=5, reset_timeout_s=30
  by default) are placeholders and should be tuned once we know the
  pilot's real rate limits and SLA.
- This ADR will be superseded or amended once real endpoint behavior is
  observed against the sandbox environment.
