# ADR 0041: Recover a Worker from OFFLINE on Heartbeat, Only When It Holds No Job

## Status

Accepted

## Context

`MarkDeadWorkersService` marks any worker OFFLINE once its heartbeat
lapses past `HEARTBEAT_TIMEOUT`, regardless of whether that worker
currently holds a running job. Every existing path back from OFFLINE
to IDLE, `Worker.recover()`, is triggered exclusively by job-recovery
services: `RecoverExpiredLeaseService` (a lease expired),
`RecoverOfflineNodeService` (the worker's node went offline), and
`CreateWorkerService` (the worker re-registers, e.g. its agent
process restarted).

A worker with no `running_job` that simply misses its heartbeat
window and then resumes heartbeating, the dashboard's own
`useWorkerHeartbeatKeeper` going idle overnight in a backgrounded
browser tab is a real, observed instance of this, has no path back
to IDLE at all. `WorkerHeartbeatService.execute()` calls
`Worker.heartbeat()`, which only ever updated `last_seen_at`. Reaching
a live, correctly-idle worker required an operator to notice it was
stuck OFFLINE and manually re-register it, discarding and recreating
what is, in every respect except its status field, a perfectly
healthy worker.

## Decision

`Worker.heartbeat()` now recovers the worker to IDLE directly, but
only when both conditions hold: status is OFFLINE, and `running_job`
is `None`.

The `running_job is None` guard is deliberate and load-bearing, not
incidental. A worker can be OFFLINE while still holding a
`running_job`, `MarkDeadWorkersService` does not check for one before
marking a worker offline. In that case, `RecoverOfflineNodeService`
may already be reassigning that exact job to a different worker by
the time a late heartbeat from the original worker arrives. If
`heartbeat()` recovered status unconditionally, that reassignment
could race a stale heartbeat: the original worker would return to
IDLE, appear available for new work, while a reference to a job it no
longer legitimately owns, or that has already been handed elsewhere,
still needs to be cleared by reconciliation first. This is the same
shape of race ADR 0034, ADR 0036, and ADR 0038 closed for lease
identity: a stale actor's belief about what it holds must never be
trusted over the system's authoritative, reconciled state, one layer
up here at the worker level rather than the lease level.

`recover()` remains the only path for a worker that was OFFLINE with
a job attached; it is unconditional by design, since it is only ever
called by a reconciliation service that has already decided, based on
real state (an expired lease, an offline node), that the job is being
taken away regardless of what the worker itself believes.

## Consequences

A worker that goes OFFLINE while genuinely idle now self-heals the
moment its heartbeat resumes, no manual re-registration required.

A worker that goes OFFLINE while holding a job still requires
reconciliation, `RecoverOfflineNodeService` or a future re-registration
via `CreateWorkerService`, to return to IDLE. This is correct: that
worker's status cannot be trusted to self-report recovery while an
unresolved job ownership question exists.

This does not change `MarkDeadWorkersService`, `RecoverExpiredLeaseService`,
or `RecoverOfflineNodeService`. It closes a gap those services were
never responsible for: recovery of a worker that never had anything
for reconciliation to reclaim in the first place.
