# ADR 0032: Move Cluster Tick Execution Off the Event Loop

## Status

Proposed

## Context

`_run_cluster_loop()`'s own docstring already names this exact risk
and defers it: `ClusterTickService.execute()` runs synchronously,
including any real subprocess execution `JobExecutionService`
performs. At the time that docstring was written, every job created
through the public API had no command (ADR 0012), so `execute()`
resolved instantly and the risk was inert.

ADR 0028 closed that gap: any authenticated caller can now set a
real, arbitrary command on a job through the public `CreateJobRequest`
API. The condition the docstring named as the trigger for revisiting
this decision has already happened, verified directly tonight: a job
running `sleep 10` genuinely blocks for its full ten seconds inside
`ClusterTickService.execute()`, which runs inside `_run_cluster_loop`'s
single background `asyncio` task.

Because that task runs on the same event loop as every HTTP request
this server handles, a single long-running job now stalls the entire
API for its full execution duration; no request of any kind, health
checks, dashboard polling, other job submissions, can be served while
one job's subprocess is running. This is not a theoretical scaling
concern; on a busy cluster running normal, real workloads, it is the
default behavior every tick.

## Decision

`_run_cluster_loop()`'s call to `cluster_tick_service.execute()` moves
to a worker thread via `asyncio.to_thread`, exactly as the docstring
it replaces already proposed. The loop `await`s that call before
proceeding to reconciliation and sleeping, preserving the existing
strict, sequential tick ordering; this change alters where the work
runs, not when.

`ReconciliationLoop.execute()` is left as a direct, synchronous call,
not moved to a thread. Reconciliation never executes a job's command;
its work (marking dead workers, reclaiming expired leases, recovering
offline nodes) is bounded, repository-bound, and fast by construction.
Moving it would add thread-hop overhead with no corresponding benefit,
and would depart from this ADR's own reasoning: move what can
genuinely block for an unbounded, caller-controlled duration, not
everything in the loop.

This relies on `PostgresJobRepository` and friends being backed by
`psycopg_pool.ConnectionPool`, which is explicitly designed to hand
out connections safely across threads; no repository code changes are
needed for this to be safe.

## Consequences

### Positive

- Closes the exact risk `_run_cluster_loop`'s own docstring named and
  deferred, now that its stated trigger condition (real commands
  reachable through the public API) has actually happened.
- The API remains responsive to every other request, including
  submitting or querying other jobs, while one job's command runs for
  an arbitrarily long duration.
- No change to tick ordering, retry semantics, or any domain logic;
  this is purely a concurrency-model change at the presentation layer.

### Negative

- Two cluster ticks can no longer be assumed to run in strict
  temporal isolation from every other thread in the process the way a
  single-threaded event loop guarantees by construction. This is safe
  given `ConnectionPool`'s own thread-safety guarantees, but it is a
  real shift worth naming rather than treating as free.
- A job with no configured timeout, or a very long one, still
  occupies a thread from the default thread pool for that entire
  duration. This bounds the *event loop's* exposure, not the
  worker-fleet's total execution capacity; a cluster running many
  long jobs concurrently could still exhaust the thread pool. Worth
  revisiting if that ever becomes the actual bottleneck, rather than
  solving it preemptively here.

## Alternatives Considered

### Move only JobExecutionService.execute() to a thread, not the whole tick

Rejected.

Would require threading that decision through
`ClusterTickService.execute()` and `WorkerExecutionLoop.execute()`,
both of which are also called synchronously and tested as such
throughout the existing suite. Moving the outer call in
`_run_cluster_loop` achieves the same effect (the event loop is never
blocked by a real subprocess) without touching either service's
signature or its extensive existing test coverage.

### Rewrite JobExecutionService to use asyncio subprocess APIs directly

Rejected, at least for now.

Would remove the thread-hop entirely, but requires converting
`JobExecutionService.execute()` and its callers to `async def`,
touching `WorkerExecutionLoop`, `ClusterTickService`, and every test
that calls them synchronously today. `asyncio.to_thread` gets the
same event-loop-safety property with a one-line change at a single
call site, at the cost of a thread per concurrent execution rather
than a purely async one. Worth revisiting if thread-pool exhaustion
(see Consequences, Negative) ever becomes real.
