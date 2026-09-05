# ADR 0031: Reclaim a Job Abandoned Mid-Cancellation

## Status

Accepted

## Context

ADR 0029 introduced `CANCELLING` as a real, visible status for a job
whose cancellation has been requested but not yet confirmed by the
worker actually executing it. That ADR's own Consequences section
named a gap it deliberately deferred rather than silently assumed
away: reconciliation's existing reclaim path (ADR 0011) targets jobs
that are `SCHEDULED` or `RUNNING` when their worker dies, and does
not cover `CANCELLING`.

The gap is real, not theoretical. `Job.reclaim()` only accepts
`SCHEDULED` or `RUNNING` as starting states; calling it on a
`CANCELLING` job raises `InvalidJobTransition`.
`RecoverExpiredLeaseService` already catches that exception for jobs
that left a reclaimable state through some other path (e.g. the
scheduler's own `unschedule()`), logs a warning, and moves on,
correctly treating that case as "nothing left to reconcile." But a
`CANCELLING` job whose worker died is not nothing left to reconcile:
its lease is gone, no worker will ever confirm its cancellation, and
without this fix it is left permanently stranded in `CANCELLING`,
with no further tick ever revisiting it.

## Decision

`Job.reclaim()` gains an explicit branch for `CANCELLING`: reclaiming
a job in this state transitions it directly to `CANCELLED`, sets
`completed_at`, and clears `assigned_node_id`, the same bookkeeping
`reclaim()` already performs for its other terminal outcome (`FAILED`
when retries are exhausted).

This does not consume a retry attempt. `reclaim()`'s existing retry
accounting exists to stop a single unhealthy node from causing a job
to be endlessly reassigned and re-abandoned; that reasoning applies
to a job that is trying to run, not to one a caller already asked to
stop. A job caught in `CANCELLING` when its worker died was already
being cancelled on purpose. The dead worker didn't prevent that
outcome, it just failed to confirm it. Finalizing the job as
`CANCELLED` here reports the actual, intended outcome; retrying it
would mean starting a fresh execution attempt the caller never asked
for and had already asked to stop.

`RecoverExpiredLeaseService` records the accurate event for this
case: `JobCancelled`, not the generic `JobReclaimed` it records for
the `SCHEDULED`/`RUNNING` path. The event stream, and the dashboard's
Activity Feed built on it, should describe what actually happened to
the job, not the mechanism (lease expiry) that happened to be how it
was discovered.

## Consequences

### Positive

- Closes a real, previously-named gap: a job can no longer be
  permanently stranded in `CANCELLING` by a worker dying before it
  confirms the kill.
- The fix lives in the same place, and follows the same shape, as
  `reclaim()`'s existing terminal-outcome branch (retries exhausted →
  `FAILED`), rather than introducing a second, parallel mechanism.
- No retry is consumed for a cancellation, keeping retry accounting
  meaningful: it now exclusively reflects attempts to actually run a
  job, not attempts to stop one.

### Negative

- A `CANCELLING` job's worker dying and a `CANCELLING` job's
  subprocess being killed successfully now both end in `CANCELLED`,
  indistinguishable from each other in the job's final status alone.
  The event history (`JobCancelled` via this path vs. via
  `ReportJobOutcomeService.cancel()`) is the only place that
  distinction survives. Worth revisiting if that distinction ever
  needs to be queryable without walking event history.

## Alternatives Considered

### Requeue the job (transition back to QUEUED) instead of CANCELLED

Rejected.

This is what happens to a `SCHEDULED`/`RUNNING` job today, and it's
correct there because that job's owner never asked it to stop, the
infrastructure failed it. A `CANCELLING` job is different: cancellation
was already requested before the worker died. Requeuing it would
silently overrule that request and start a fresh execution attempt
nobody asked for.

### Fail the job (transition to FAILED) instead of CANCELLED

Rejected.

`FAILED` implies the job's own execution went wrong. A job that was
already being cancelled, on request, when its worker happened to die
didn't fail on its own merits; recording it as `CANCELLED` reports
the true, intended outcome rather than miscategorizing a requested
stop as a failure.
