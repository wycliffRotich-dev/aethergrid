# 0048. Generalize GovAPIClient into ResilientAPIClient for Reuse Beyond One Integration

## Status

Accepted

## Context

ADR 0047 introduced `GovAPIClient`, built ahead of a possible pilot
integration with an important third party whose endpoint, auth
mechanism, and rate limits were not yet known. On review, nothing in
its actual design, retry with backoff, a circuit breaker, mTLS and
OAuth2 support, structured error types, config validation, was
specific to that one integration. The name and the folder it lived in,
`integrations/gov_client/`, were the only things tying it to a single
counterparty.

Naming a general-purpose resilient HTTP client after one specific
integration creates two problems. First, it invites duplication: the
next time AetherGrid needs to talk to a slow, rate-limited, or
unreliable third party, whoever picks up that work is unlikely to look
inside a folder named for an unrelated pilot and reuse what is already
there, they will more likely write a second, near-identical client.
Second, it ties the code's identity to an outcome that has not
happened yet. If the pilot does not proceed, a client still named
after it reads as a dead end rather than as reusable infrastructure.

## Decision

Rename and relocate the client before any other integration comes to
depend on it, while it is still cheap to do:

- `GovAPIClient` becomes `ResilientAPIClient`
- `GovAPIClientConfig` becomes `ResilientClientConfig`
- `GovAPIError` becomes `ResilientAPIError`
- The module moves from `integrations/gov_client/` to
  `integrations/resilient_client/`
- Docstrings and inline comments are reworded to describe the general
  problem, talking to a third party you do not control and cannot
  fully see into, rather than one specific counterparty
- All other exception types (`ClientError`, `RateLimitError`,
  `ServerError`, `RetryExhaustedError`, `ConfigError`,
  `CircuitOpenError`, `AuthError`) and the retry, circuit breaker, and
  validation logic itself are unchanged, since none of it was ever
  government-specific to begin with

ADR 0047 is left as written. It is a historical record of a decision
made at a specific time for a specific reason, and rewriting it to
match the new name would misrepresent what was actually known and
decided at that point. This ADR is the follow-up that explains what
changed and why, the same pattern ADR 0042 used to follow up on ADR
0041.

## Consequences

Positive:

- The client's name now describes what it does rather than who it was
  first built for, so the next integration that needs retry, backoff,
  and a circuit breaker is far more likely to be found and reused
  instead of reimplemented
- If the original pilot does not proceed, the work is not stranded
  under a name that only made sense for it
- The rename happened before any other code depended on the old names,
  so the change is a pure rename with no call sites to migrate

Negative and follow-ups:

- Anyone reading ADR 0047 in isolation will see `GovAPIClient` and
  `GovAPIClientConfig`, names that no longer exist in the codebase.
  This ADR exists specifically to close that gap for a reader who
  follows the trail from 0047 forward
- The next real integration that reuses `ResilientAPIClient` should
  confirm the retry, circuit breaker, and Retry-After defaults chosen
  for the original pilot still make sense for a different third
  party's actual behavior, rather than assuming they transfer as is
