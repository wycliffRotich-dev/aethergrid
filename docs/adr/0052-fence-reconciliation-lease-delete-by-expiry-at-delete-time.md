# ADR 0052: Fence Reconciliation's Lease Delete by Expiry at Delete Time

## Status

Accepted

## Context

`RecoverExpiredLeaseService.execute()` reads a snapshot of every
lease via `LeaseRepository.list()`, then decides what to reclaim
based on that snapshot: `lease.is_expired()` is checked once, against
the `expires_at` value the snapshot captured. Reclaiming a job calls
`reclaim_job()` (`job_execution_support.py`), which calls
`lease_repository.delete(job.id)`, an unconditional delete keyed only
on `job_id`.

This left a real window between the snapshot read and the delete. A
worker's background renewal thread calls `LeaseRepository.renew()`
directly against the database, independent of reconciliation's own
pass. If that renewal lands after the snapshot was read but before
reconciliation's delete runs, the lease is no longer actually expired
by the time it is deleted, yet the delete still fires, since it never
re-checks expiry at the moment it executes. The worker's job is then
reclaimed out from under its current, legitimate owner, for a reason
that had already stopped being true by the time it happened.

This is the same class of bug ADR 0034 fenced for
`ReleaseLeaseService`, which deleted a lease keyed only on
`worker_id` with no check that it was still the same lease the
caller originally acquired. ADR 0034 through ADR 0038 fenced
release, renewal, and outcome reporting by lease identity. None of
them touched reconciliation's own delete call, since the bug there is
staleness of a snapshot read, not confusion between two different
leases. Confirmed directly: neither the Postgres nor the in-memory
lease repository contract test suite had any coverage at all of
`delete()`'s behavior against an already-renewed lease before this
ADR.

`RecoverExpiredLeaseService`'s own docstring already documented
delete-before-touch-job as the fix for a related but distinct race,
a renewal landing after the delete. Deleting first correctly closes
that direction. It does nothing for a renewal that already happened
before the delete, since the delete itself never re-checks anything.

## Decision

`LeaseRepository` gains a new abstract method,
`delete_if_expired(job_id) -> bool`. It deletes the lease for
`job_id` only if it is still expired at the moment of deletion, not
at some earlier read, and returns whether a row was actually removed.

Postgres implements this as a single conditional `DELETE ... WHERE
job_id = %s AND expires_at < %s`, atomic at the database level. The
in-memory implementation checks `lease.is_expired()` immediately
before popping the entry, matching the same semantics without a
database transaction to rely on.

`reclaim_job()` gains an optional `lease_already_deleted: bool =
False` parameter. When `True`, it skips its own unconditional
`delete()` call, since the caller has already performed a fenced
delete and confirmed it actually removed a row.

`RecoverExpiredLeaseService.execute()` now calls
`delete_if_expired()` itself, before doing anything else with the
lease. If it returns `False`, meaning the lease was renewed since the
snapshot was read, the loop logs and moves to the next lease without
touching the worker or the job at all. If it returns `True`, the
worker and job are processed as before, and `reclaim_job()` is called
with `lease_already_deleted=True` so the lease is not deleted a
second time.

`delete()` itself is left unconditional and unchanged. Existing
callers that already fence lease identity upstream of the delete
(`ReleaseLeaseService`, per ADR 0034) do not need this check
repeated at the repository layer; adding it there as well would be
redundant, not incorrect, but the smallest change is to add fencing
only where a real gap was found.

## Alternatives Considered

### Change `delete()`'s own semantics to always check expiry

Rejected. `delete()` is called by more than reconciliation. Some
callers (`ReleaseLeaseService`) delete a lease that is not expired at
all, by design, as part of a legitimate release. Making `delete()`
itself conditional on expiry would break those callers outright
rather than fix reconciliation's specific gap.

### Re-check `list()` immediately before every delete, without a new repository method

Rejected. This still leaves a window between the re-check and the
delete, just a smaller one, and it is two round trips instead of one
atomic conditional delete. The database can enforce this correctly in
a single statement; re-checking in application code cannot close the
race, only narrow it.

### Wrap the whole reconciliation pass in a single database transaction

Rejected as out of scope for this specific gap. A single transaction
around the whole pass would change reconciliation's isolation and
locking behavior far beyond what this bug requires, and would need
its own dedicated design and ADR given how much of the reconciliation
loop currently assumes autocommit, per-repository-call semantics.
The conditional delete closes the actual race without touching that
broader question.

## Consequences

### Positive

- The specific race is closed and proven closed: a lease renewed
  between reconciliation's snapshot read and its delete now survives,
  verified at the repository level on both backends and at the
  service level with a test that simulates the exact interleaving.
- No change to any other caller's behavior. `ReleaseLeaseService`,
  `RenewLeaseService`, and every other consumer of `LeaseRepository`
  are untouched.
- Matches this codebase's existing pattern for this exact problem
  shape (`renew()`'s `LeaseNotFoundError` on a already-deleted lease,
  from ADR 0014), rather than introducing a new one.

### Negative

- `RecoverOfflineNodeService` was not touched by this change and is
  not proven safe against an equivalent race. It keys off
  `node.is_alive()`, not lease expiry, and never checks
  `lease.is_expired()` at all, so this specific fencing pattern does
  not directly apply to it. Whether a worker on a node judged offline
  can still have a lease renewal in flight, independent of the node's
  own heartbeat mechanism, has not been investigated. This is an
  open question, not an assumption of safety, and is worth its own
  pass rather than folding into this ADR.
- `reclaim_job()`'s signature grew by one optional parameter. Every
  existing caller besides `RecoverExpiredLeaseService` is unaffected,
  since the parameter defaults to `False` and preserves the prior
  unconditional-delete behavior exactly.
