# ADR 0046: Health Endpoint Bypasses the Repository Pattern for a Fast, Explicit Timeout

## Status

Accepted

## Context

`/health` (formerly the misleadingly-named `/` "Health endpoint", which
just returned a static welcome message) needs to prove the configured
storage backend is actually reachable, not just that the process is
running. The obvious first approach was routing this through the
existing `NodeRepository` abstraction, calling its cheap, read-only
`list()` method the same way every other route in the application
reaches the database.

That approach has a real problem, discovered by inspection of
`psycopg_pool.ConnectionPool`'s constructor: its `timeout` parameter,
which bounds how long `pool.connection()` will wait for a usable
connection, defaults to 30.0 seconds. Neither `app/infrastructure/database.py`
nor `dependencies.py`'s `_build_repositories()` overrides this default
anywhere. That 30-second patience is correct for normal application
code, which should tolerate a brief connectivity blip rather than fail
a user-facing request outright. It is the wrong value for a health
check, whose entire purpose is to report bad news fast.

`NodeRepository` is a domain-level interface, implemented identically
by `PostgresNodeRepository`, `SqliteNodeRepository`, and
`InMemoryNodeRepository`. Adding a `timeout` parameter to `list()` to
special-case one caller's needs would leak an infrastructure concern
(connection pool timeouts) into a domain interface where two of three
implementations have no meaningful notion of a timeout at all.

## Decision

`/health` bypasses `NodeRepository` entirely for the connectivity
check. `_build_repositories()` now also returns the raw
`ConnectionPool` (or `None` under `sqlite`/`memory`, where there is no
network round-trip to hang on), exposed via a new `get_connection_pool()`
accessor in `dependencies.py`, matching the existing `get_*` singleton
pattern used by `get_reconciliation_loop()` and `get_cluster_tick_service()`.

`/health` calls `pool.connection(timeout=HEALTH_CHECK_TIMEOUT_SECONDS)`
directly, with `HEALTH_CHECK_TIMEOUT_SECONDS = 2.0`, and runs a trivial
`SELECT 1` to confirm the connection actually works, not just that one
was handed back. Under `sqlite` or `memory`, where `pool` is `None`,
the check is skipped and the endpoint reports healthy unconditionally,
since there is no comparable failure mode to protect against.

## Alternatives Considered

### Extend NodeRepository's interface with a timeout parameter

Rejected. This would force `InMemoryNodeRepository` and
`SqliteNodeRepository` to accept a parameter that means nothing to
them, purely to serve one caller's needs. It also would not have
worked cleanly regardless: `list()`'s existing contract and its
callers throughout the application (the scheduler loop, reconciliation
services) correctly expect the patient, 30-second default. Overloading
the same method with two different timeout behaviors depending on the
caller's intent is a worse design than giving the health check its own
path.

### Build a second, dedicated ConnectionPool with a short timeout

Rejected. This would mean maintaining two separate pools against the
same database from the same process, doubling the connection overhead
and introducing a second place where pool configuration (`min_size`,
`max_size`, `kwargs`) needs to be kept in sync with the first. Passing
a per-call `timeout` to the existing pool's own `connection()` method
achieves the same fast-fail behavior with no duplicate resource.

## Consequences

### Positive

- `docker compose ps` now reports `neuromesh` as `(healthy)` or
  `(unhealthy)`, matching `postgres`, instead of a bare `Up` that says
  nothing about whether the application can actually do its job.
- The failure path is fast and bounded under the most common,
  observed failure mode: a cleanly stopped Postgres process, which
  raises `psycopg.errors.AdminShutdown` on an already-open connection.
  Measured repeatedly at 1.3ms to 17ms, and separately at exactly
  2001-2002ms when the pool has no live connection and must attempt a
  fresh one against an unreachable host, confirming the explicit
  `timeout=2.0` is honored precisely in both failure shapes.
- No new dependency: the fix uses `psycopg_pool`'s existing per-call
  `timeout` parameter on `connection()`, already present in the
  installed version, rather than adding new configuration surface.

### Negative

- `/health` now depends on `ConnectionPool` directly, a step outside
  the domain/infrastructure boundary every other route in the
  application respects by going through a repository. This is a
  deliberate, narrow exception, not a precedent: any future health-adjacent
  endpoint that needs the same fast-fail property should extend this
  same accessor, not reach for `NodeRepository` and hope nobody adds a
  slow default to it later.
- One anomalous result was observed once during testing: a single
  `/health` request under a stopped Postgres took approximately 28.86
  seconds to return, matching the pool's original 30-second default
  rather than the requested 2-second override. Two subsequent, similarly-
  constructed trials both completed in the expected ~2001ms, and the
  pool's own internal stats confirmed the 2-second timeout is correctly
  enforced by `psycopg_pool` at every layer traced (`getconn`,
  `_getconn_with_check_loop`, `_get_ready_connection`, `AttemptWithBackoff`).

  **Root cause, since confirmed by reproduction:** the official
  Postgres Docker image performs a two-phase startup on a fresh
  volume -- a temporary instance runs `initdb` and the init scripts,
  then shuts down completely before the real, final instance starts.
  `pg_isready`, and therefore Compose's `depends_on: condition:
  service_healthy`, can report healthy against that temporary
  instance. `neuromesh`'s container was observed starting during this
  window; the pool's first connection attempts landed in the gap
  between the temporary instance's shutdown and the real instance's
  startup, triggering `psycopg_pool`'s internal retry/backoff
  (`AddConnection` tasks, `WARNING`-level `error connecting in
  'pool-1'`) until the real instance came up. Reproduced directly with
  debug-level pool logging across a genuine cold volume/container
  rebuild: the gap measured ~5.2 seconds in one run (temporary-instance
  shutdown at 06:30:02.229, real instance ready at 06:30:07.458),
  producing a single `/health` request at ~906ms instead of the usual
  ~1.7ms -- the same mechanism as the original ~28.86s observation, at
  a smaller magnitude consistent with a warmer disk cache on that
  particular rebuild (the shutdown checkpoint's own `sync=4.442s` in
  that run's logs shows this phase is disk-bound and will vary).

  **Fix:** `lifespan()` (`app/presentation/api.py`) now calls
  `pool.wait(timeout=30.0)` via `asyncio.to_thread` before starting the
  cluster tick task and yielding control to Uvicorn. The application no
  longer reports `Application startup complete` -- and therefore never
  accepts a single request, including Docker's own healthcheck -- until
  the pool has a confirmed, live connection. This does not fix
  Postgres's two-phase startup, which is upstream image behavior, not
  ours to change; it fixes the actual defect on this side, which was
  trusting Compose's `service_healthy` as sufficient proof of
  readiness for this specific image. Verified by re-running the same
  cold-start reproduction: `Application startup complete` now logs
  only after `database system is ready to accept connections`, and the
  first `/health` request returns in ~56ms (one real connection
  handshake) rather than racing the outage.
- The background cluster tick loop (`app/presentation/api.py`,
  `TICK_INTERVAL_SECONDS = 1.0`) shares the same pool and correctly
  continues to use its 30-second default timeout, since it should
  tolerate a longer outage rather than fail fast. Under a sustained
  outage, this means the tick loop and `/health` requests may compete
  for the same limited connection slots (`max_size=10`) concurrently,
  though `/health`'s own explicit timeout was observed to be honored
  correctly under this exact concurrent load in two separate trials.
