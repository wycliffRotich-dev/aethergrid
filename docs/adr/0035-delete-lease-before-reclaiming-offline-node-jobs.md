# ADR 0035: Delete a Job's Lease Before Reclaiming It in RecoverOfflineNodeService

## Status

Accepted

## Context

`RecoverExpiredLeaseService` deletes a job's lease row before
calling `job.reclaim()`, explicitly, with a comment naming exactly
why: doing it first closes a window where a worker's background
renewal thread could successfully renew a lease reconciliation has
already decided to reclaim, letting a worker believe it still owns
a job that's about to be, or already has been, handed to someone
else.

`RecoverOfflineNodeService`, the sibling reconciliation service
responsible for the equivalent recovery when a *node* rather than a
*lease* goes stale, never adopted that pattern. It reclaimed the job
and saved it, but never touched the lease repository at all, and
did not even hold a reference to one.

The consequence is deterministic, not a race: `AcquireLeaseService.
execute()` refuses to create a new lease when
`get_by_job_id(job.id)` already finds one, raising a bare
`ValueError`. A job recovered through the offline-node path kept
its stale lease row forever, since nothing in this codebase's
automatic reconciliation cycle (`ReconciliationLoop` runs exactly
`MarkDeadWorkersService`, `RecoverExpiredLeaseService`,
`RecoverOfflineNodeService`, nothing else) ever deleted it.
`RemoveOfflineNodeService`, the only code path that does delete
node/worker rows (and would cascade-delete a lease via
`leases.worker_id ON DELETE CASCADE`), is a separate,
presumably operator-triggered path reachable only through
`POST` on the nodes router, never called by the automatic
reconciliation loop. So every job assigned to a worker on a node
that went offline was permanently stranded: correctly returned to
`QUEUED`, but never again schedulable, since the very next
`AcquireLeaseService` call for it would fail, forever.

Verified directly: a test constructing a real lease, running
`RecoverOfflineNodeService.execute()` against the unpatched code,
and asserting the lease still existed and a follow-up
`AcquireLeaseService.execute()` call genuinely raised, passed
against the unfixed service, confirming the strand as real, not
theoretical.

This is the third time this shape has been found in this codebase,
not the first:

- ADR 0033: `StartJobService` established the correct pattern
  (persist a job immediately after `worker.start()`);
  `WorkerExecutionLoop` didn't inherit it, independently
  rediscovered.
- ADR 0034: lease renewal (`renew()`) already enforced identity
  fencing; lease release (`ReleaseLeaseService`) didn't, checking
  only worker identity, independently found while investigating a
  gap ADR 0014 had named.
- This ADR: `RecoverExpiredLeaseService` established the correct
  pattern (delete the lease before reclaiming); its sibling
  `RecoverOfflineNodeService` didn't inherit it.

In each case, a correct pattern already existed, proven and tested,
somewhere else in the codebase, and a sibling or adjacent code path
simply didn't adopt it. Three independent instances of the same
shape is worth naming as a pattern in its own right, not just
fixing as three unrelated bugs.

## Decision

`RecoverOfflineNodeService` gains a `LeaseRepository` dependency
and calls `lease_repository.delete(job.id)` immediately before
`job.reclaim()`, in the same position, for the same reason,
`RecoverExpiredLeaseService` already does. Wired in
`app/presentation/dependencies.py`; every existing test
construction site updated to match.

No new abstraction was introduced to structurally prevent a fourth
occurrence of this shape. That was considered and deliberately
deferred; see Alternatives Considered.

## Consequences

### Positive

- Closes a real, deterministic bug: every offline-node recovery
  previously stranded its job permanently. Now the job is both
  correctly requeued and genuinely reschedulable.
- Matches the existing, already-tested pattern exactly, no new
  mechanism, no new failure mode.
- Verified by a test that failed (proved the strand) against
  unpatched code before any production code changed, and now
  passes by asserting the fixed behavior: lease gone, reacquire
  succeeds.

### Negative

- This is the third instance of "a sibling service didn't inherit
  an established correct pattern." Fixing each occurrence
  individually, as this ADR does, does not prevent a fourth. That
  risk is named here explicitly rather than assumed closed by this
  fix alone.

## Alternatives Considered

### Extract a shared "reclaim and clean up" function, the way ADR 0033 extracted persist_job_started

Considered, deliberately not done here.

`RecoverExpiredLeaseService` and `RecoverOfflineNodeService` reclaim
under different surrounding conditions, the former discovers work
via lease expiry and must delete first to close a renewal race; the
latter discovers work via node liveness and has no equivalent
renewal-thread race to close, since a node going offline doesn't
have a background renewal thread racing against it the way an
individual lease does. Forcing both into one shared function risks
hiding that the two delete-before-reclaim orderings exist for
different reasons, not the same one. The three-line body
(`lease_repository.delete(job.id)` then `job.reclaim()`) is small
enough that duplicating it with a clear comment in each place, as
done here, was judged clearer than a shared abstraction that would
need to explain two different justifications for the same three
lines. Worth revisiting if a fourth reclaim-adjacent service needs
the same shape.

### Add a contract test asserting every service that calls job.reclaim() also clears the job's lease

Considered, deferred.

Would structurally prevent a fourth occurrence rather than relying
on manual audit, which is exactly what surfaced this one. Not built
here because it requires reflecting over call sites of `reclaim()`
across the codebase, a meaningfully larger testing-infrastructure
investment than this fix itself, and no third occurrence had yet
been confirmed at the time this alternative was weighed. Worth
revisiting seriously if a fourth instance of this shape is ever
found; three independent occurrences is close to the threshold
where a structural guard stops being premature.
