# ADR 0033: Persist a Job's RUNNING Transition Immediately After worker.start()

## Status

Accepted

## Context

`Worker.start()` transitions its held job to RUNNING entirely in
memory. `WorkerRepository.save()` only ever writes the `workers`
table; it does not persist the `Job` object `worker.running_job`
points to. Any caller that calls `worker.start()` and does not
separately call `job_repository.save(worker.running_job)`
immediately afterward leaves the `jobs` table row showing SCHEDULED
for the job's entire real execution, no matter how long that
execution actually runs.

This has already been discovered once, independently, in
`StartJobService`, whose own inline comment documents finding it
while running a real standalone agent (ADR 0019) against real
Postgres for the first time: every prior job completion went
through `WorkerExecutionLoop`'s in-process path instead, "which
never hits this gap." That comment was correct about `StartJobService`
being fixed. It was wrong, or at least premature, about
`WorkerExecutionLoop` being exempt: it never hit the gap only
because nothing had yet exercised that path against a real,
non-shared-reference-backed repository with a command that runs
long enough to observe. `InMemoryJobRepository.get_by_id()` returns
the exact same object reference on every call, so any code racing
against it happens to appear consistent regardless of missing
persistence; `SqliteJobRepository` and `PostgresJobRepository` both
reconstruct a fresh `Job` from a row on every read, so they do not
mask this.

Verified directly: a test driving `WorkerExecutionLoop.execute()`
against a real, temp-file-backed `SqliteJobRepository`, with a
command that runs briefly and a genuinely separate connection
simulating a concurrent `CancelJobService` call, hit
`InvalidJobTransition: Cannot transition from SCHEDULED to
CANCELLING` from that concurrent call, because the database still
showed SCHEDULED while the subprocess was actually running.

This has two concrete, user-facing consequences once a job's
command can run for any real, observable duration (ADR 0028 made
that the normal case, not a theoretical one):

1. `GET /jobs/{id}` reports SCHEDULED for the job's entire actual
   execution window, not RUNNING.
2. `CancelJobService.execute()` checks `job.is_running()` against
   that stale row. Reading False, it falls to the immediate-cancel
   branch (`job.cancel()`), writing CANCELLED straight to the
   database while the subprocess is still alive and was never
   asked to stop. The renewal thread's own cancellation check looks
   for CANCELLING, not CANCELLED, so it never notices; the
   subprocess finishes on its own, and the loop's unconditional
   final `save()` overwrites the incorrect CANCELLED row with the
   real outcome. Net effect: a cancellation request against a
   genuinely running, dashboard-managed job is silently ignored,
   with no error, no `cancellation_requested_at`, no event
   recorded.

## Decision

The invariant is named once, as a shared function, not duplicated a
second time in `WorkerExecutionLoop` the way it would be by simply
copying `StartJobService`'s inline fix:

```python
def persist_job_started(
    job_repository: JobRepository,
    worker: Worker,
) -> None:
    """
    Persist the job a worker just started, immediately.

    worker.start() mutates worker.running_job to RUNNING in
    memory, but WorkerRepository.save() only ever writes the
    workers table, never the job itself. Any caller that
    transitions a worker to RUNNING must call this right
    after, or the jobs table row stays SCHEDULED for the
    job's entire real execution (ADR 0033). This has already
    been independently rediscovered once; the goal of naming
    it here is that the next code path that starts a worker
    does not have to rediscover it a third time.
    """
    if worker.running_job is not None:
        job_repository.save(worker.running_job)
```

Both `StartJobService` and `WorkerExecutionLoop` call this
immediately after `worker.start()`, replacing their own inline
duplicate of the same three lines with a single shared call and a
single place the reasoning lives.

## Consequences

### Positive

- Closes a real gap in the in-process execution path: `GET
  /jobs/{id}` now reflects RUNNING promptly, matching what the
  worker is actually doing.
- Closes the silent-cancellation-ignored gap: `CancelJobService`
  now correctly reads RUNNING for a genuinely executing
  dashboard-managed job and takes the `request_cancellation()`
  branch instead of the immediate-cancel branch.
- The invariant now lives in exactly one place. A third code path
  that starts a worker inherits the fix automatically instead of
  needing to rediscover it.

### Negative

- One additional repository write per worker start, on a path that
  already performs several. Negligible cost against the correctness
  gap it closes.
- This does not, by itself, close the narrower race already named
  separately: a cancellation request that arrives after the
  renewal thread's last periodic check but before the subprocess
  exits naturally can still resolve to COMPLETED/FAILED with
  `cancellation_requested_at` silently dropped by the loop's final
  unconditional `save()`. That is a distinct, narrower gap,
  worth its own follow-up, not fixed by ensuring RUNNING itself is
  persisted promptly.

## Alternatives Considered

### Duplicate the three-line fix directly in WorkerExecutionLoop, matching StartJobService's own inline shape

Rejected.

This is exactly how the gap was found a second time: the fix and
its reasoning existed in one file's comment and were invisible to
the next file that needed the same fix. Duplicating it again
would leave the invariant undiscoverable a third time, for the
next new execution path, rather than closing that discoverability
gap now.

### Have Job.save() imply persisting via Worker, so WorkerRepository.save() writes both tables

Rejected.

Would couple two repository interfaces that this codebase
otherwise keeps deliberately separate (ADR: domain owns scheduling
policy, not persistence-layer coupling between aggregates). A
worker's own repository writing another aggregate's table as a
side effect is a surprising, implicit dependency; an explicit call
at the one point the invariant actually applies (immediately after
worker.start()) keeps the persistence boundary between Job and
Worker exactly where it already is everywhere else in this
codebase.
