# ADR 0015: API Key Authentication

## Status

Accepted

## Context

Every route was previously reachable with no authentication at all: any caller could create jobs, register nodes and workers, drain a node, or query cluster state without identifying itself in any way.

ADR 0012 deferred exposing `Job.command` specifically because doing so over an endpoint with no authentication would mean shipping unauthenticated remote code execution. That was the concrete blocker this ADR addresses. Building authentication does not, by itself, decide whether `Job.command` should now be exposed; see Consequences.

Two credential approaches were considered: JWT (stateless, self-verifying) and opaque server-issued tokens looked up against a repository. JWT's core value, avoiding a database hit per request, is exactly the property not wanted here. Revocation has to be immediate: a leaked or decommissioned credential can't wait for a token's expiry. Immediate revocation with JWT still requires maintaining a denylist, which means paying for a stateful store anyway while gaining none of statelessness's benefit.

## Decision

- Opaque, server-issued API keys, not JWTs. `ApiKey.issue()` generates a `secrets.token_urlsafe(32)` secret, hashes it with SHA-256 before persisting (`ApiKey.hash_secret`), and returns the plaintext exactly once, the same convention GitHub and Stripe use for personal access tokens. The plaintext is never stored or logged. SHA-256 was chosen over a slow password hash (bcrypt/scrypt/argon2) deliberately: those exist to slow down brute-forcing low-entropy human passwords, and would instead impose a real, unnecessary cost on every authenticated request against a secret that is already 256 bits of random data.
- `ApiKeyRepository` follows the same contract-testing discipline as every other repository in this system: an abstract interface, an in-memory implementation, a PostgreSQL implementation, and a shared behavioral contract test suite run against both. There is deliberately no SQLite implementation. Local development already consolidated onto the same PostgreSQL backend used in production; adding a SQLite path for this one repository would reintroduce the exact environment drift that consolidation eliminated. The `sqlite` storage backend falls back to `InMemoryApiKeyRepository`, the same pattern already used there for `Worker` and `Lease`.
- Two different repository interaction patterns are used, matching the two that already exist elsewhere in this codebase for the same reasons. Revocation is cold-path: fetch the entity, call its `revoke()` domain method, persist the whole entity via `save()` (an upsert), mirroring how `Job` transitions are persisted. Recording that a key was just used is hot-path, called on every authenticated request: `ApiKeyRepository.mark_used()` is a targeted `UPDATE` that never loads the entity at all, mirroring `LeaseRepository.renew()`. Both raise `ApiKeyNotFoundError` if the row is gone rather than silently recreating it, the same reasoning `renew()` already uses to guard against resurrecting a lease reconciliation already reclaimed.
- Every route requires a valid key, including `/api-keys` itself. An earlier draft of this left key creation unauthenticated, which would have let any caller mint themselves a valid credential before any auth existed at all. Fixed by gating the `api_keys` router behind its own `require_api_key` dependency. This creates a genuine bootstrapping requirement: `scripts/issue_api_key.py` is the only way to mint the first key, run locally with direct repository access, never over HTTP.
- The same `require_api_key` FastAPI dependency was added to every existing router (`jobs`, `nodes`, `workers`, `cluster`, `events`), not only the new one, and applied to every route on each, including reads. An unauthenticated cluster-state or job-list endpoint is still real surface area on a distributed job scheduler, even though gating reads too meant the dashboard's existing unauthenticated calls stopped working.

## Consequences

Every route in the system now requires a valid API key. The live dashboard, built against these endpoints with no auth header, no longer works unmodified; sending a credential from the frontend is necessary follow-up work, not yet done.

`Job.command` remains unexposed. Authentication existing removes the specific blocker ADR 0012 named, but does not by itself answer whether arbitrary command execution should be exposed to any authenticated caller. That is now a separate, deliberate product decision, not a technical gate waiting on infrastructure, and it has not been made yet.

`ApiKeyRepository` is the fifth aggregate validated by the shared contract test suite pattern, and the first to deliberately support only two backends instead of three, a precedent the next repository added to this system can point to instead of re-arguing.

Existing presentation-layer tests (`tests/presentation/`) were written before auth existed and call routes directly with no credential. Rather than modify eight existing test files individually, a single `tests/presentation/conftest.py` overrides `require_api_key` via FastAPI's `app.dependency_overrides` for that directory only, so those tests keep verifying what they were written to verify, route behavior, without carrying a token that has nothing to do with what they are testing.

Per-caller scoping (any valid key can revoke any other key, including itself), rate limiting, and key rotation beyond manual issue and revoke are explicitly out of scope for this decision. Fine for a single-operator system; not fine the moment a second untrusted caller exists.
