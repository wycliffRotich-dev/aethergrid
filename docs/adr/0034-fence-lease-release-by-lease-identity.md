# ADR 0034: Fence Lease Release by Lease Identity, Not Just Worker Identity

## Status

Accepted

## Context

ADR 0014 made lease renewal a strict conditional update, so a
renewal can never resurrect a lease reconciliation already
reclaimed. That ADR's own Consequences section named a gap it
deliberately left open rather than silently assumed closed:
`job_repository.save(job)` has no fencing check at the point a
job's final state is written. Protection there is entirely
inferred from renewal having not failed, not an explicit check
of lease identity at save time. ADR 0014 judged closing that
out of scope, since the renewal-failure path already closed the
specific races that ADR addressed.

Tracing that gap surfaced something worse, upstream of the save
itself: `ReleaseLeaseService.execute(worker_id)` looks up
whatever lease is currently on record for a worker and deletes
it, keyed only on `worker_id`. It never verifies that lease is
the same one the caller originally acquired and has been
renewing. `Lease.id` is a stable UUID minted once at
`Lease.create()` and never reassigned by `renew()`, so "is the
lease I started with still the current lease for this job" is a
real, cheap, checkable question, and nothing today asks it.

The concrete failure this enables, verified directly with a
test before any fix landed:

1. Worker W acquires `Lease A` for `Job 1`. Execution begins.
2. `Lease A` expires without being renewed in time (a slow
   renewal thread, a missed heartbeat) and reconciliation
   reclaims `Job 1`, deleting `Lease A`.
3. Worker W is later, legitimately, assigned a different job,
   `Job 2`. `AcquireLeaseService` creates a brand-new `Lease B`
   for `(W, Job 2)`.
4. The original, stale caller for `Job 1`, unaware anything
   happened, finally finishes and calls
   `release_lease_service.execute(worker_id=W)`.
5. `ReleaseLeaseService` finds `Lease B`, the only lease on
   record for W, and deletes it. It has no way to know this
   isn't the lease it was asked to release.
6. The stale caller sees release "succeed" and, under both
   `WorkerExecutionLoop` and `ReportJobOutcomeService`'s
   existing "release succeeded, so it's safe to persist" logic,
   persists `Job 1`'s stale result.
7. `Job 2`'s legitimate, currently-executing worker just had
   its real lease deleted out from under it, for a reason with
   nothing to do with `Job 2` at all.

This is a real cross-job lease-theft path, not a restatement of
the save-time gap ADR 0014 named. It sits one level upstream:
every downstream `save()` currently trusts release succeeding as
its safety signal, and that signal itself carried no identity
check.

## Decision

`ReleaseLeaseService.execute()` gains a required
`expected_lease_id: UUID` parameter. It still looks up whatever
lease is on record for the worker via `get_by_worker_id`, but
now compares that lease's `id` against `expected_lease_id`
before deleting anything. A mismatch, including the lease having
vanished entirely, means whatever is on record no longer belongs
to this caller, and raises `LeaseNotFoundError`, the same
exception `renew()` already raises for the equivalent race, so
every existing caller's "drop it on the floor" handling covers
this for free.

Both call sites that persist a job's outcome under an assumed
lease now capture that lease's identity explicitly, before
trusting it:

- `WorkerExecutionLoop.execute()` fetches the current lease via
  `get_by_worker_id` once, at the top, immediately after
  confirming the worker holds a running job. This is the
  earliest point the loop can be said to hold a lease, and
  capturing it here closes the full window the cross-job-theft
  scenario lives in: the job's entire execution duration.
- `ReportJobOutcomeService` fetches the lease similarly, via a
  new `_current_lease_id` method, immediately before `_finish()`
  releases it. This narrows the window to a single request's
  handling time rather than a whole external round trip.

`LeaseRepository` is now a required dependency of
`WorkerExecutionLoop` (previously it had none) and of
`ReportJobOutcomeService` (previously it only received a
pre-wired `ReleaseLeaseService`, never the repository directly).
Both are wired in `app/presentation/dependencies.py`, and every
test construction site for either service was updated to match.

## Scoped, Named Limitation

This does not close the gap for the standalone-agent path (ADR
0019) as fully as the in-process path. `ReportJobOutcomeService`
narrows its own window to one request, but the external HTTP
contract (`POST /workers/{worker_id}/jobs/{job_id}/complete`,
`/fail`, `/cancel`) does not currently carry lease identity from
the agent back to the server, so the agent itself still can't be
asked to prove which lease it believes it holds across its own
poll-execute-report round trip. Widening that would mean
changing the public API contract those endpoints expose, not
just internal wiring, and is deliberately left as a separate,
future decision rather than silently assumed solved here.

## Consequences

### Positive

- Closes a real, previously-unguarded cross-job lease-theft
  path, verified directly by a test that passed against the
  unpatched code (proving the unsafe delete actually happened)
  and now passes against the fix by asserting a raise and an
  intact replacement lease instead.
- `ReleaseLeaseService` now enforces the same identity
  discipline `renew()` has enforced since ADR 0014, closing the
  asymmetry between the two lease-mutating operations.
- Every caller of `release_lease_service.execute()` already had
  "drop the result on the floor" handling for
  `LeaseNotFoundError`-shaped failures; this reuses that
  existing idiom rather than inventing a new one.

### Negative

- `ReleaseLeaseService.execute()`'s signature is now a breaking
  change; every caller, production and test, needed updating in
  the same change. Nothing was left half-migrated.
- Does not close the equivalent gap on the standalone-agent
  HTTP path (see Scoped, Named Limitation above). That remains
  open, named, and deferred, not silently assumed solved by this
  ADR.
- One additional repository read per lease acquisition-adjacent
  call site (loop start, outcome report entry). Negligible
  against the correctness gap closed.

## Alternatives Considered

### Add the fencing check only at job_repository.save(job), as ADR 0014 originally proposed

Rejected as insufficient on its own.

Tracing the actual call path showed the more severe gap sits
one level upstream, at lease release itself, which every save
site currently trusts as its safety signal. Fencing only at
save would still allow release to delete an unrelated,
legitimately-held lease; the save-time check would need its own
separate identity comparison duplicating what release should
already guarantee. Fixing release closes both problems through
one mechanism instead of two.

### Compare lease identity by comparing timestamps or worker_id alone

Rejected.

`Lease.id` already exists, is stable across renewals, and is
exactly the identity primitive this check needs. Introducing a
second, weaker comparison (e.g. "is the lease's acquired_at
still what I remember") would be strictly worse than reusing an
identifier this codebase already trusts elsewhere.
