# 0049. Resilient Client Replays Only Requests That Are Safe to Replay

## Status

Accepted. Amends the retry policy introduced in ADR 0047.

## Context

ADR 0047 gave the client retry with backoff. Its usage guide then
documented a known limitation: every HTTP method was retried,
including POST.

That limitation was made concrete by a characterization test running
the real client against a mock partner over real HTTP. The mock
applies a payment, then loses the response with a 503. The client saw
a failure, retried, and the payment was applied a second time. The
caller received a clean success and never learned it had been charged
twice.

This matters more for this client than for most code. It talks to
systems AetherGrid does not operate and cannot inspect. A duplicated
write there is invisible from our side and hard to undo, and a
retry layer that quietly creates duplicates is worse than one that
fails loudly.

## Decision

Whether to retry is decided per request, by whether a replay can
repeat a side effect:

- Idempotent methods (GET, HEAD, OPTIONS, PUT, DELETE, per RFC 9110)
  are retried on transient failures, as before.
- A request that provably never reached the server is retried for any
  method. A refused connection or a connect timeout means nothing was
  sent, so nothing can be duplicated.
- A 429 is retried for any method, since the server declined the
  request before acting on it.
- A POST or PATCH that hits a 5xx or a read timeout is not retried by
  default. The server may already have acted.
- A call that passes `idempotency_key` is treated as safe to replay.
  The key is sent in a configurable header, `Idempotency-Key` by
  default, so a partner that deduplicates can recognize the replay.
- Callers can also widen `RetryConfig.retryable_methods` for a partner
  known to deduplicate everything.

Failures that leave it genuinely unknown whether the request took
effect set `outcome_unknown` to `True` on `ServerError` and
`RetryExhaustedError`. This tells the caller to reconcile with the
partner instead of guessing. The client also gains a `patch()` method,
which it lacked.

Alternatives considered:

- Generate an idempotency key automatically for every POST. Rejected.
  A key only makes a replay safe if the partner honors it, and the
  client cannot know that. A partner that ignores the header would
  leave the client believing replays were safe when they were not. The
  caller has to assert it, because the caller knows the partner.
- Keep retrying everything and document the risk. Rejected. It
  silently duplicates writes, and a warning in a README does not
  protect the person whose payment was charged twice.

## Consequences

Positive:

- A POST cannot be duplicated by the client's own retry logic unless
  the caller has said replaying is safe
- Failure is explicit. A caller learns the outcome is unknown and can
  reconcile, instead of receiving a false success
- Read paths and idempotent writes keep their full retry behavior

Negative and follow ups:

- A POST to a flaky endpoint now fails on the first transient 5xx
  instead of healing itself. Callers who can supply an idempotency key
  should, once the partner is confirmed to support one
- Nothing in AetherGrid calls the client yet, so no existing caller is
  affected and there is nothing to migrate
- The header name, the key lifetime, and the partner's actual
  deduplication semantics should be confirmed against the real
  integration before relying on them
- A failure that stops early for safety still counts toward the
  circuit breaker, because it still says the endpoint is unhealthy
