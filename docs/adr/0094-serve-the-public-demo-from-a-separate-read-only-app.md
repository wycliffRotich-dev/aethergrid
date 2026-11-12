# ADR 0094: Serve the Public Demo from a Separate Read-Only App

## Status

Proposed.

Related: ADR 0015, ADR 0021, ADR 0028, ADR 0064 and ADR 0078.

## Context

A public demonstration of AetherGrid needs a URL that anyone can open and
that shows real workers, jobs, leases and recovery from a dedicated demo
deployment. The dashboard today asks for an API key and says there are no
public keys, by design. That rule stays.

The existing app cannot also serve an anonymous surface:

- Every router carries require_api_key and require_rate_limit, and ADR 0064
  point 10 has tests that classify every route and send each one a request
  with no key. An anonymous route there would fail them, and the only ways
  to pass would be to weaken them or to add an anonymous kind to a table
  that has none.
- The app starts the scheduler and the in-process executor in its lifespan
  (ADR 0078). A job command is a real subprocess (ADR 0028). Anything served
  from that process shares it with the executor.
- The rate limiter is keyed on an authenticated API key (ADR 0021), so an
  anonymous caller has no identity to count against.
- The private response schemas were written for an authenticated tenant. A
  field added to one later would reach the public if the public reused it.

## Decision

1. The public surface is a separate FastAPI app in app/presentation/public/,
   with its own app object, its own entry point and its own process. It is
   not part of app.presentation.api, and it is not in the
   app.presentation.routers package, which the ADR 0064 tests scan.
2. It serves GET routes only, from an explicit list of paths. No other method
   is registered.
3. Every response model is defined in the public package. It imports no model
   from app.presentation.schemas, so a field is public only when it is
   written there on purpose.
4. It starts no cluster loop and takes no scheduler lock. No service that
   creates, changes, drains, removes, cancels or heartbeats anything is
   imported by it.
5. The tenant it reads is set in server configuration when the app is built.
   Nothing in a request chooses it.
6. It accepts no credential and issues none. The private API keeps its rule
   that there are no public keys.
7. It reads through the existing application services and repository
   interfaces. The domain gains nothing for it.

## Consequences

- A second process to deploy, monitor and stop. The private API and the
  executor are never reachable from the public one.
- Its own guard tests, with the inverse of the ADR 0064 rule: every route is
  a GET, the paths equal the allowlist, every route is rate limited, every
  response model is a public schema, and no write service is importable.
- The node-to-response mapping is written again for the public schemas, on
  purpose.
- The public app is not deployed until it has its own anonymous rate limiter
  and a read-only database role. Each gets its own ADR and brick.

## Not Claimed

- That the public demo is safe to expose. This ADR sets the boundary and
  nothing is deployed.
- That the ADR 0064 tests cover the public app. They do not, and it gets its
  own.

## Alternatives Considered

- **A public router inside the existing app.** Rejected. It fails the ADR 0064
  tests, and it puts an anonymous surface in the process that runs the
  executor.
- **A static snapshot, written as sanitised JSON on an interval and served as
  files.** Rejected as the main design. It has the smallest attack surface,
  because no public request reaches a database, but it cannot show live
  request handling, rate limits or a recovery as it happens. It stays
  available as a fallback.
- **Reuse the private response schemas.** Rejected. A field added to a
  private schema would become public with no review.

## How to Verify

The guard tests arrive with the first change after this ADR.

## Progress

2026-11-11. The public settings require a database URL and a password
file of their own, AETHERGRID_PUBLIC_DATABASE_URL and
AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE, with no defaults and no
fallback to the NEUROMESH_ names. The URL must be a postgresql:// URL
with a host and no password in it. No database access is wired yet.
