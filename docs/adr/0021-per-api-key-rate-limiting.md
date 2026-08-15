# ADR 0021: Per-API-Key Rate Limiting

## Status

Accepted

## Context

ADR 0015 explicitly deferred rate limiting: "fine for a single-operator system, not fine the moment a second untrusted caller exists." Every route already requires a valid `ApiKey` (ADR 0015), and there is no limit today on how many requests a single valid key can issue. A leaked or malicious key currently has unbounded call volume against every route, including writes.

Two axes were considered independently: what the limit key is, and where the counter lives.

Limiting by IP was rejected. Every caller already carries an authenticated identity, the `ApiKey` itself, and IP is a strictly worse identifier for this system: it breaks for callers behind shared NAT or a proxy, and it ignores the identity the system already trusts for every other decision. Limiting by `ApiKey.id` is consistent with how every other cross-cutting concern in this codebase already keys off the authenticated caller. Key issuance itself is already closed: the only way to mint a key is `scripts/issue_api_key.py`, run locally with direct repository access, never over HTTP (ADR 0015). This decision does not defend against an attacker who can already mint arbitrary keys; that would require access this system does not expose over the network in the first place.

Two storage approaches were considered for the counters themselves: an external store (Redis) or an in-memory counter local to the process. Redis buys correctness under horizontal scaling, multiple API instances sharing one view of a caller's usage, at the cost of a new infrastructure dependency this system does not otherwise have, and a network round trip on every single request. That cost mirrors the exact reasoning ADR 0015 used to reject JWT with a denylist: paying for a stateful remote lookup on every request when the system does not yet have the deployment shape that requires it. This system runs as a single process today; the README's own "What's Next" lists live multi-instance cloud deployment as future work, not current state. Introducing Redis now would be solving a scaling problem that does not exist yet, at the cost of complexity that is real today.

## Decision

- Rate limiting is enforced per `ApiKey.id`, not per IP, using the same authenticated identity every other route decision already relies on.
- Counters are in-memory, local to the running process, using a token bucket per key rather than a fixed or sliding window. Token bucket was chosen over fixed window specifically because a fixed window allows a caller to burst up to 2x the intended limit at the window boundary; token bucket does not have that failure mode, and it naturally expresses a burst allowance (a caller can spend saved-up capacity quickly, then is throttled to the steady refill rate) rather than a hard cliff.
- This is explicitly scoped to the current single-process deployment. If and when this system runs as more than one instance, an in-memory counter no longer gives a correct global view of a caller's usage, and that will require revisiting this decision, most likely toward the Redis-backed approach considered and rejected here. This ADR does not claim to solve that; it solves the problem this system actually has today.
- Enforcement is a second FastAPI dependency, `require_rate_limit`, chained after `require_api_key` on every route, the same way `require_api_key` itself was added uniformly across every router in ADR 0015, not applied selectively.
- A caller that exceeds its bucket receives `429 Too Many Requests` with a `Retry-After` header indicating how long until the next token is available, following the same `HTTPException`-plus-headers pattern `require_api_key` already uses for `401`.
- Bucket capacity and refill rate are fixed per key today, not configurable per caller. Per-key configurable limits are explicitly out of scope for this decision, the same way ADR 0015 scoped per-caller permission differences out of its own decision.

## Consequences

Every authenticated route now has a bounded request rate per key, closing the gap ADR 0015 named and deferred.

This does not protect against a distributed abuse scenario using many different valid keys, or against abuse that stays under the per-key limit but is still unwanted, that is a separate concern (anomaly detection, global rate limits) not addressed here.

The limiter's state is lost on process restart, meaning a caller's bucket resets to full whenever the API restarts. This is an accepted tradeoff of the in-memory approach, not a defect, consistent with choosing to solve today's actual deployment shape rather than build for a multi-instance future that does not exist yet.

If this system moves to multiple concurrent instances, this decision must be revisited. The in-memory counter will silently stop being correct, each instance will enforce its own independent limit rather than one shared limit, without raising any error, so this needs to be caught by an operator recognizing the deployment shape has changed, not by anything in the code itself.
