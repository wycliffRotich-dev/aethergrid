# ADR 0045: Fleet Agents Use One API Key Per Agent, Not a Shared Key

## Status

Accepted

## Context

ADR 0044 made the standalone agent (`scripts/run_agent.py`, ADR
0019) survive a control plane restart, overload, or rate limiting
through unbounded retry with capped backoff and full jitter. Its
own Consequences section named a problem retry cannot fix:

> Retries do not raise the rate limit. ADR 0021 gives one shared
> key a bucket of 60 tokens refilling at 10 per second, and an
> idle agent makes about 0.6 requests per second, so a shared key
> supports on the order of 14 concurrent agents before throttling
> begins. Backoff makes an agent behave well when throttled, but
> it cannot remove that ceiling. Fleet-scale credentials need a
> separate decision.

This is that decision.

ADR 0021 already rate-limits per `ApiKey.id`, not per caller
identity in general, specifically because it keys off the same
authenticated identity every other cross-cutting concern in this
codebase already trusts. `scripts/issue_api_key.py` already takes
an arbitrary `label` and is already the only way to mint a key
(ADR 0015), cheap to run as many times as needed. Nothing in
either mechanism assumes, or requires, exactly one key for the
whole system.

What actually causes the ~14-agent ceiling is not a limitation of
ADR 0021's design, it is that `run_agent.py`'s own usage docstring
and the README's agent-startup instructions only ever demonstrate
minting a single key and exporting it as `AETHERGRID_API_KEY`, with
no distinction drawn between "one key for local development" and
"one key per fleet member." An operator following the documented
usage as written arrives naturally at the shared-key bottleneck
ADR 0044 described, without ever making an explicit choice to.

## Decision

Each agent process is issued its own API key, labeled by the node
it runs against, and no two agents share a key.

- `scripts/issue_api_key.py` is run once per node, for example
  `python scripts/issue_api_key.py "agent-<node-id>"`, and the
  resulting key is exported as that node's `AETHERGRID_API_KEY`.
- This requires no change to `app/application/services/rate_limiter_service.py`,
  `app/presentation/auth.py`, or any other application or
  infrastructure code. ADR 0021's per-`ApiKey.id` token bucket
  already gives each independently labeled key its own 60-token
  bucket refilling at 10 per second, which already removes the
  fleet-wide ceiling ADR 0044 identified, because that ceiling
  was a property of key-sharing, not of the rate limiter itself.
- `scripts/run_agent.py`'s module docstring and `Usage:` block,
  and the README's agent section, are updated to show per-node
  key issuance as the documented pattern, not a single shared
  export.
- A shared key across multiple agents remains possible; nothing
  in the system prevents it. It is no longer the documented or
  intended pattern for running more than one agent.

## Consequences

### Positive

- Removes the ~14-agent ceiling ADR 0044 named, using only
  mechanisms that already exist and are already tested.
- Each agent's rate-limit bucket is now independent, so one
  agent's retry storm during an incident cannot exhaust another
  agent's throughput against the API.
- Per-key labeling (already supported by `issue_api_key.py`)
  gives each key an identifiable owner in `/api-keys` listings,
  which a shared key does not.

### Negative

- Operators running an existing fleet against a shared key must
  reissue and redistribute per-node keys to benefit from this;
  nothing forces that migration automatically.
- Key management now scales with fleet size: N agents means N
  keys to issue, store, and eventually revoke and rotate, rather
  than one. `scripts/issue_api_key.py` has no batch-issuance or
  fleet-wide revocation tooling today; that gap is left to a
  separate decision if fleet size makes manual issuance
  impractical.

## Alternatives Considered

### Raise the shared key's bucket capacity or refill rate

Rejected. This trades one fixed ceiling for a different fixed
ceiling and reintroduces exactly the failure mode ADR 0021 chose
token bucket to avoid at the single-caller level: a large shared
bucket lets any one agent (or a compromised key) consume the
entire fleet's allowance, since the rate limiter cannot
distinguish which agent within a shared key is issuing requests.

### Per-agent limits enforced some other way (e.g. a request header identifying the agent)

Rejected. This would duplicate the identity and enforcement model
ADR 0021 already built around `ApiKey.id`, for no benefit over
issuing a real key per agent, which the existing mechanism already
supports without modification.

## References

- ADR 0015: API Key Authentication
- ADR 0019: Standalone Worker Agent Process
- ADR 0021: Per-API-Key Rate Limiting
- ADR 0044: Agent Retries Transient Failures With Capped Backoff and Jitter
