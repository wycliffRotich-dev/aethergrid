# ADR 0039: Fully Reclaim an Abandoned Job on Worker Re-registration

## Status

Accepted

## Context

ADR 0030 made worker registration idempotent per node: re-registering
against a node that already has a worker reclaims the existing `Worker`
via `Worker.recover()` rather than minting a duplicate. `recover()`
forgets any `running_job` and returns the worker to `IDLE`.

ADR 0030 explicitly named this a known, accepted tradeoff: "Reclaiming
silently discards whatever the previous agent process's `running_job`
was, exactly as `recover()` already does for reconciliation. This is an
accepted, pre-existing tradeoff, not a new one." That statement was
accurate when it was written. It described `RecoverExpiredLeaseService`
and `RecoverOfflineNodeService`'s behavior at the time, both of which
also called `worker.recover()` on an abandoned job without releasing
the node's allocated resources or deleting the stale lease.

Both of those services were subsequently fixed to correctly delete the
job's lease and release the node's resources before calling
`recover()`. Nothing changed in `CreateWorkerService`. ADR 0030's
stated rationale, mirror reconciliation's semantics, now points at
behavior that no longer exists: reconciliation's `recover()` calls are
always paired with lease deletion and node release; `CreateWorkerService`'s
is not.

This produces two problems, one already familiar to this codebase, one
new.

The familiar one: a node's advertised capacity permanently shrinks by
the abandoned job's resources every time an agent restarts mid-job,
the same shape as the gap just closed in `RecoverExpiredLeaseService`
and `RecoverOfflineNodeService`.

The new one, and the more serious one: `AcquireLeaseService` fences
leases by `job_id` only, not `worker_id`, and `Worker.accept()` only
checks `is_idle()`. Once `CreateWorkerService` marks a reclaimed worker
`IDLE`, nothing prevents the scheduler from assigning it a brand new
job before the old job's lease, 30 seconds by default, expires. When
that old lease does expire, `RecoverExpiredLeaseService` looks the
worker up by `worker_id` and calls `recover()` on it again, wiping
`running_job`, which by then points at the new, legitimately executing
job, not the old one. The worker's tracking is now false: the system
believes it holds no job while a real subprocess is still running on
the agent machine for one. This is not a capacity leak, it is corrupted
state for a job actively in flight.

## Decision

Before `CreateWorkerService` calls `existing.recover()`, it fully
reclaims any `running_job` the existing worker holds, using the same
sequence reconciliation now uses: delete the job's lease, release the
node's resources, call `job.reclaim()`, save both, then recover the
worker. This requires threading `JobRepository`, `LeaseRepository`,
and `NodeRepository` into `CreateWorkerService`, none of which it
previously depended on.

A worker is never left `IDLE` while an unreclaimed job or a live lease
still points at it.

## Rationale

This does not reverse ADR 0030. The decision to preserve `WorkerId`
across a restart and to treat an abandoned job as unrecoverable to its
original execution attempt both still hold. What changes is only that
the abandonment is now handled completely, the same three-step
sequence already proven correct and tested in both reconciliation
services, rather than partially, which is what let a corrupted-state
race become possible.

## Consequences

### Positive

- Closes the same resource-leak shape already fixed twice today, now a
  fourth confirmed instance in this codebase's history (alongside ADR
  0033, 0034, 0035).
- Closes a genuine correctness race: a currently running job's tracking
  can no longer be silently corrupted by a stale reconciliation pass
  reacting to an unrelated, earlier job on the same worker.
- Reuses an already-tested sequence rather than inventing new recovery
  logic.

### Negative

- `CreateWorkerService` gains three new constructor dependencies it did
  not previously need, widening its responsibility beyond pure worker
  registration into job/lease/node cleanup. Considered and accepted:
  the alternative is leaving the reclaim incomplete, which is the exact
  gap this ADR closes.

## Alternatives Considered

### Leave CreateWorkerService as-is, rely on RecoverExpiredLeaseService alone

Rejected. The lease will eventually expire and reconciliation will
release the node's resources correctly, closing the capacity leak on
its own. It does nothing about the correctness race: the worker is
already `IDLE` and reassignable the instant `CreateWorkerService` runs,
long before the old lease expires.

### Prevent Worker.accept() from accepting new work until any prior lease is confirmed gone

Deferred. Would close the race from a different angle, at the cost of
adding a lease-existence check to the domain's job-acceptance path,
a broader change than this specific gap requires. The reclaim-before-recover
sequence closes it entirely without touching `accept()`.

## References

- ADR 0030: Idempotent Worker Registration Per Node
- ADR 0033: Persist a Job's RUNNING Transition Immediately After worker.start()
- ADR 0034: Fence Lease Release by Lease Identity, Not Just Worker Identity
- ADR 0035: Delete a Job's Lease Before Reclaiming It in RecoverOfflineNodeService
