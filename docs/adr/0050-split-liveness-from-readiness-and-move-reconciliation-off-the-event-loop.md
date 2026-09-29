# ADR 0050: Split Liveness From Readiness, and Move Reconciliation Off the Event Loop

## Status

Accepted

## Context

ADR 0032 moved `ClusterTickService.execute()` to a worker thread but
left `ReconciliationLoop.execute()` as a direct, synchronous call on
the event loop, reasoning that its work is "bounded, repository-bound,
and fast by construction." That reasoning holds only while the
database is reachable.

Reproduced directly: with the `postgres` container stopped,
`ReconciliationLoop.execute()` calls into repositories backed by the
shared `psycopg_pool.ConnectionPool` (`dependencies.py`,
`_build_repositories()`), which has no `connect_timeout` override and
falls back to the pool's default connection timeout of 30 seconds
(the same default ADR 0046 identified and deliberately bypassed for
`/health`, but reconciliation was never routed around it). Called
directly on the event loop, that 30-second wait blocks every request
the server handles, not only DB-backed ones: `curl`ing `/openapi.json`,
which touches no repository at all, measured two stalls of 29.6s and
28.7s during a single sustained outage.

The tick loop's own 1-second sleep between ticks means this repeats
roughly once a minute for the duration of any outage: ~30s blocked,
then ~30s responsive, on a cycle, for as long as the database stays
down.

This has a second, more serious consequence. `docker-compose.yml`'s
`neuromesh` healthcheck polled `/health`, which correctly returns 503
when the database is unreachable (ADR 0046). About 30 seconds into any
outage, the container is marked unhealthy, in addition to being
unresponsive. Under any orchestrator that restarts unhealthy
containers, a database outage becomes an application restart loop,
which is the opposite of the behavior wanted from a container that has
correctly stayed up and is simply waiting for a dependency to return.

`/health`'s design (ADR 0046) is correct for what it answers: can this
process do useful work right now. The bug is that the container
healthcheck was asking that question, when what a healthcheck's
restart decision actually needs is a different question: is this
process alive at all.

## Decision

Two changes:

1. `ReconciliationLoop.execute()` moves to a worker thread via
   `asyncio.to_thread`, called the same way `ClusterTickService.execute()`
   already is (ADR 0032). This is the direct fix for the freeze: the
   event loop is no longer blocked while any repository call, tick or
   reconciliation, waits on the connection pool. Tick ordering is
   unchanged; reconciliation still runs after the tick and before the
   loop's sleep. It simply no longer does so on the event loop itself.

2. A new `/livez` endpoint is added: an `async def` with no
   dependencies, in particular no `ConnectionPool`, returning
   `{"status": "alive"}` unconditionally. `docker-compose.yml`'s
   `neuromesh` healthcheck now polls `/livez` instead of `/health`.
   `/health` is unchanged and continues to serve as the
   database-aware readiness check ADR 0046 designed it to be; nothing
   currently polls it as a container healthcheck, but it remains
   available for any external monitor or load balancer that wants
   readiness rather than liveness.

This establishes liveness and readiness as two distinct, permanent
questions for this application. Liveness must never depend on the
database, or on anything else that can be down while the process
itself is fine; that is precisely the case it exists to distinguish.
Readiness may depend on the database, because that is the question it
exists to answer. Any future health-adjacent endpoint should be
written against one of these two questions explicitly, not a blend of
both.

## Consequences

### Positive

- Closes the freeze directly: a 130-second soak test against a
  stopped `postgres` container, sampled every 2 seconds against
  `/openapi.json`, showed a worst-case latency of 0.124s after this
  change, against two stalls of ~29s and ~28s before it.
- `docker compose ps` now reports `neuromesh` as `(healthy)`
  throughout a database outage, confirmed against the same soak test.
  A database outage no longer risks triggering a restart of an
  otherwise-healthy application container.
- Corrects ADR 0032's "bounded... by construction" claim for
  reconciliation specifically: bounded by the pool's timeout, not by
  reconciliation's own logic, and that bound is 30 seconds by default,
  not the "fast" the original ADR assumed.
- No behavior change to reconciliation's own logic, ordering, or
  retry semantics; like ADR 0032, this is a concurrency-model change
  at the presentation layer only.

### Negative

- The specific reasoning against threading reconciliation in ADR 0032
  ("would add thread-hop overhead with no corresponding benefit") no
  longer holds; that overhead is now accepted in exchange for the
  event-loop-safety property. Worth naming since ADR 0032's stated
  principle, move what can block for an unbounded, caller-controlled
  duration, technically still argues against this: reconciliation's
  duration is not caller-controlled. Reconciliation is threaded anyway
  because "bounded by the pool's default timeout" turned out to mean
  30 seconds, which is unbounded in any practical sense from the event
  loop's perspective.
- Does not address thread-pool exhaustion under a sustained outage,
  which ADR 0046 already flagged as a known risk for the tick loop and
  which now also applies to reconciliation: each thread-hopped call
  still waits up to the pool's default timeout before returning, and
  holds a worker thread from Python's default thread pool for that
  duration. Enough concurrent DB-backed requests during a long enough
  outage could still exhaust that pool. Worth a dedicated pass if
  sustained outages in practice turn out to be common enough to matter,
  rather than solved speculatively here.
- Does not verify recovery behavior after the database returns beyond
  what the existing test suite already covers; the soak test used to
  validate this ADR stops short of confirming steady-state behavior
  once `postgres` restarts mid-cycle.

## Alternatives Considered

### Give reconciliation's repository calls their own short, explicit timeout, the way ADR 0046 did for `/health`

Rejected for this repository call, not in general. ADR 0046's fast-fail
timeout is right for a check whose entire purpose is to report bad
news quickly. Reconciliation's purpose is the opposite: to eventually
repair state once the database returns, so a short timeout would only
convert a slow success into a fast, and more frequent, failure,
without solving the event-loop-blocking problem at all if it stayed on
the event loop. Threading removes the blocking regardless of how long
the call takes, which is the actual requirement here.

### Point the container healthcheck at `/health` but treat "unhealthy" as acceptable during an outage

Rejected. This depends entirely on the orchestrator not acting on the
`unhealthy` status, which is not a property of this application and
not something to assume of every environment this container runs in
now or in the future. `/livez` makes the container's liveness genuinely
independent of the database, rather than making it dependent and hoping
nothing downstream reacts to that dependency.

### Remove `/health` and make it the same as `/livez`

Rejected. This would erase the distinction ADR 0046 built `/health`
specifically to draw, and remove the only endpoint that answers "can
this process reach its storage backend," which remains useful to
external monitors, dashboards, and any future readiness-gated routing
even though nothing in this repository's own compose file consumes it
as a container healthcheck today.
