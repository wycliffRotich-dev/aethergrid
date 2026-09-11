# ADR 0038: Fence Lease Renewal by Lease Identity, Not Just Worker Identity

## Status

Accepted

## Context

ADR 0034 fenced lease *release* against a real cross-job
lease-theft path: `ReleaseLeaseService` used to look up
whatever lease was currently on record for a worker and act on
it, keyed only on `worker_id`, with no check that the caller's
belief about which lease it held still matched reality. ADR
0036 closed the same gap for outcome reporting, since the
external agent HTTP contract carried no lease identity at all.

`RenewLeaseService.execute(worker_id)` has the identical shape,
and neither prior ADR touched it:

```python
def execute(self, worker_id, duration=DEFAULT_LEASE_DURATION):
    lease = self._lease_repository.get_by_worker_id(worker_id)
    if lease is None:
        raise NoActiveLeaseError(worker_id)
    self._lease_repository.renew(lease.id, duration)
```

It resolves "the lease" by `worker_id` alone and renews
whatever it finds, with no comparison against any identity the
caller actually holds. `WorkerExecutionLoop.keep_lease_alive()`
calls this in a loop for the entire duration of a job's
execution, and the standalone-agent HTTP endpoint
(`POST /workers/{worker_id}/lease/renew`) exposes the exact
same call, with no request body, so external agents renew the
same unfenced way, repeatedly, for as long as they run.

The concrete failure this enables is the same cross-job shape
ADR 0034 named for release, but silent instead of destructive:

1. Worker W acquires `Lease A` for `Job 1`. Execution begins,
   and a renewal thread starts calling `renew(worker_id=W)` on
   an interval.
2. `Lease A` expires without being renewed in time and
   reconciliation reclaims `Job 1`, deleting `Lease A`.
3. Worker W is later, legitimately, assigned a different job,
   `Job 2`. `AcquireLeaseService` creates a brand-new `Lease B`
   for `(W, Job 2)`, with its own renewal thread.
4. `Job 1`'s original renewal thread, unaware anything
   happened, fires its next renewal tick and calls
   `renew(worker_id=W)`.
5. `RenewLeaseService` finds `Lease B`, the only lease on
   record for W, and renews it. It has no way to know this
   isn't the lease it was asked to renew.
6. `Job 1`'s stale thread believes its own renewal succeeded
   and keeps running, unaware its real lease is long gone.
   Meanwhile `Job 2`'s lease has just been extended by a
   caller with no legitimate claim to it, silently, with
   nothing to catch or log the mismatch.

Unlike ADR 0034's release-time theft, nothing is deleted here,
which is precisely what makes this the more dangerous of the
two: a caller renewing the wrong lease sees no error, produces
no exception for any existing "drop it on the floor" handling
to catch, and can mask a real failure. If `Job 2`'s own renewal
thread has a bug and stops renewing correctly, a leftover
renewal call from `Job 1`'s zombie thread keeps `Lease B` alive
anyway, hiding the exact failure reconciliation exists to
detect.

This is not scoped as an internal-only gap the way ADR 0034
deferred the agent HTTP path for release. Renewal is the
standalone agent's actual heartbeat mechanism (ADR 0019):
called repeatedly, for a job's entire runtime, not once at a
terminal event. `GetWorkerResponse.lease_id` (ADR 0036) already
hands an agent the lease identity it should be renewing, and
`ReportJobOutcomeRequest.lease_id` (ADR 0036) already requires
that same agent to echo it back on completion. Renewal is the
one remaining call in that same lifecycle still missing the
matching check, on both the internal loop and the external
contract.

## Decision

`RenewLeaseService.execute()` gains a required
`expected_lease_id: UUID` parameter, following ADR 0034's exact
mechanism. It still looks up whatever lease is on record via
`get_by_worker_id`, but now compares that lease's `id` against
`expected_lease_id` before renewing anything. A mismatch,
including the lease having vanished entirely, raises
`LeaseNotFoundError`, the same exception `ReleaseLeaseService`
already raises for the equivalent race.

Both call sites now capture lease identity explicitly before
trusting it, matching ADR 0034's precedent:

- `WorkerExecutionLoop.keep_lease_alive()` captures the current
  lease's id once, at the point the loop starts renewing,
  immediately after `AcquireLeaseService` returns it, and
  passes that same id on every renewal tick for the job's
  entire execution.
- `POST /workers/{worker_id}/lease/renew` now requires a
  request body carrying `lease_id: UUID`, mirroring
  `ReportJobOutcomeRequest`'s existing shape (ADR 0036). An
  agent must state which lease it believes it is renewing, the
  same value it received from `GetWorkerResponse.lease_id` when
  it last checked in, not have the server look that up on its
  behalf.

A mismatch or missing lease surfaces as `409 Conflict` at the
HTTP layer, the same status `renew_lease` already returns for
`NoActiveLeaseError`, so no new response shape is introduced.

## Consequences

### Positive

- Closes a real, previously-unguarded cross-job lease
  masking path, silent rather than destructive, but capable of
  hiding a genuine reconciliation failure behind an
  illegitimate renewal.
- Extends the identity discipline ADR 0034 established for
  release, and ADR 0036 established for outcome reporting, to
  the third and final lease-mutating operation, closing the
  full set rather than leaving renewal as the odd one out.
- Unlike ADR 0034's scoped limitation, this closes the gap on
  the standalone-agent path in the same change, not as a
  deferred follow-up, since renewal's repeated, long-lived
  nature made deferring it a materially larger live exposure
  than deferring release's one-time terminal call was.

### Negative

- `RenewLeaseService.execute()`'s signature is a breaking
  change; every caller, production and test, needed updating
  in the same change.
- `POST /workers/{worker_id}/lease/renew` is a breaking API
  contract change for any external agent already calling it
  without a body. Acceptable pre-wide-rollout, per the same
  reasoning ADR 0028 and ADR 0036 already applied: today,
  exactly one operator holds any credential capable of running
  an agent against this API.

## Alternatives Considered

### Defer the agent HTTP contract change, matching ADR 0034's scoped limitation

Rejected.

ADR 0034 deferred the agent path because release is a one-time,
terminal call; the exposure window was narrow and the fix could
follow later without materially increasing risk in the
meantime. Renewal has no such narrow window: it is called on a
fixed interval for a job's entire runtime, so any external
agent doing real renewal today would be exercising the unfenced
path continuously, not occasionally. Deferring it here would
be deferring the majority of this ADR's actual value.

### Detect the mismatch only via logging, without raising

Rejected.

A silent renewal-of-the-wrong-lease is exactly the failure mode
that already produces no signal today; adding a log line
without raising keeps the caller's behavior unchanged and adds
observability nobody is positioned to act on in the failure
path itself. Raising `LeaseNotFoundError` reuses handling every
caller already has for the equivalent release-time race.
