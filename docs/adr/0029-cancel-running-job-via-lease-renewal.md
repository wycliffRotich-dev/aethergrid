# ADR 0029: Cancel a Running Job by Reusing Lease Renewal for Delivery

## Status

Accepted

## Context

`CancelJobService` exists today, but `Job._ALLOWED_TRANSITIONS` only
permits `CANCELLED` from `QUEUED` or `SCHEDULED`. A job that has
already reached `RUNNING` cannot be cancelled at all: calling
`job.cancel()` on it hits `_transition_to` with no valid path and
raises. There is no code path anywhere that reaches a live subprocess
and asks it to stop.

That gap is structural, not an oversight in `CancelJobService`.
`JobExecutionService.execute()` blocks on a single
`process.communicate(timeout=...)` call with no loop and no hook for
an external signal to interrupt it early. Whatever calls `execute()`
gets control back only on natural completion or on the existing
timeout path. There is currently no way for anything outside that
method to reach the `Popen` it owns.

Both real callers of `JobExecutionService`, `WorkerExecutionLoop`
(in-process scheduling) and `run_job()` in `scripts/run_agent.py`
(the standalone agent, ADR 0019), already run a second thread
alongside the one blocked in `execute()`: a lease-renewal loop that
calls `POST /workers/{worker_id}/lease/renew` on a fixed interval for
the entire duration of execution (ADR 0014). That thread already
exists, already runs concurrently with execution, and already talks
to the server on a schedule. It is the only piece of either call site
positioned to learn about a cancellation request while execution is
still in progress.

## Decision

Cancellation is delivered by extending the existing lease-renewal
response, not by adding a new endpoint or a new polling loop. When a
worker's lease-renewal call finds that the job it's renewing for has
a pending cancellation, the response says so. This reuses a channel
that already fires on a known interval for the entire life of every
running job, matching the reasoning ADR 0019 already used to reject
push delivery: don't introduce a new delivery mechanism with its own
failure modes when an existing, trusted one already covers the same
ground.

`JobStatus` gains a new state, `CANCELLING`, reachable only from
`RUNNING`. This is a visible, explicit mid-cancellation state, not a
side flag on an otherwise-unchanged `RUNNING` job: a job caught
between "cancellation requested" and "subprocess confirmed dead" is a
real, distinct state a dashboard or API consumer should be able to
see, not an implementation detail.

`CANCELLING` can resolve to `COMPLETED`, `FAILED`, **or** `CANCELLED`,
not only `CANCELLED`. This is required by a real race: cancellation
is delivered on the next lease-renewal tick, not instantly, so a
subprocess can legitimately finish on its own in the window between a
cancellation being requested and the renewal thread next checking for
it. Whichever actually happens first wins. If the process completes
or fails before the kill signal reaches it, that real outcome is
recorded, exactly as `WorkerExecutionLoop` already drops a stale
subprocess result on the floor when `lost_lease` fires mid-execution
(this codebase's existing idiom for "the world moved on before this
result could be trusted"), applied here to a new case rather than
inventing a second one.

`JobExecutionService.execute()` gains an optional `cancel_event:
threading.Event | None` parameter. Its internal wait changes from one
blocking `communicate(timeout=...)` call to a short-interval polling
loop checking both elapsed time and `cancel_event.is_set()` each
iteration. When the event fires first, execution follows the same
two-stage `SIGTERM`-then-`SIGKILL` escalation already built and
tested for the timeout path, just triggered by a different signal
reaching the same, already-proven exit route.

`JobExecutionResult` gains a `cancelled: bool` field, parallel to the
existing `timed_out: bool`, so callers can distinguish "we killed it
because someone asked us to" from "we killed it because it overran
its timeout", the same reasoning that field's own docstring already
gives for keeping timeout and generic failure distinguishable.

Both `WorkerExecutionLoop` and `run_agent.py`'s `run_job()` gain a
`cancel_event`, created alongside their existing `stop_renewing`
event, checked and set inside their existing `keep_lease_alive()`
loop when a renewal response reports a pending cancellation, and
passed into `job_execution_service.execute(...)`. No new thread is
introduced at either call site.

## Consequences

### Positive

- Closes a real, previously-unreachable gap: a running job can now
  actually be cancelled, not just a queued or scheduled one.
- No new delivery mechanism. Cancellation rides an existing,
  already-trusted channel that already runs on a known interval for
  the full lifetime of every running job.
- The race between natural completion and cancellation taking effect
  is named explicitly and resolved with an idiom this codebase
  already uses elsewhere, not a new judgment call invented for this
  feature.
- `CANCELLING` being a real, visible status means a dashboard or API
  consumer can show "cancellation in progress" honestly, instead of a
  job that looks like it's still running with no indication anything
  was requested.

### Negative

- Cancellation is not instant. It's bounded by the lease-renewal
  interval (`RENEWAL_INTERVAL_SECONDS`, roughly a third of
  `DEFAULT_LEASE_DURATION`), so there's a real, bounded delay between
  requesting a cancellation and the subprocess actually receiving
  `SIGTERM`. This is a deliberate trade-off for reusing an existing
  channel rather than building a lower-latency one; worth revisiting
  if that delay proves too long in practice.
- Reconciliation's existing reclaim logic (ADR 0011) currently
  targets `RUNNING` jobs whose worker died. It needs to also cover
  `CANCELLING`, a worker can die mid-cancellation exactly as it can
  die mid-execution, and that path is not fully specified by this
  ADR; it's flagged here as a known follow-up, not silently assumed
  to already work.
- `CancelJobService` needs a second, distinct path for `RUNNING`
  jobs (transition to `CANCELLING`, do not touch the subprocess
  directly) alongside its existing immediate-cancel path for `QUEUED`
  and `SCHEDULED`. This is a real branch in previously simple logic
  worth reviewing carefully, since getting it wrong in either
  direction (silently no-op on a running job, or incorrectly forcing
  an immediate `CANCELLED`) is worse than the gap this ADR closes.

## Alternatives Considered

### Poll the process handle from inside the caller instead of passing an event into JobExecutionService

Rejected.

Would require `JobExecutionService` to hand its `Popen` object back to
the caller, leaking a subprocess implementation detail across the
application/domain-adjacent service boundary this codebase otherwise
keeps clean. Passing a `threading.Event` in keeps `JobExecutionService`
fully self-contained: it still owns the entire lifecycle of the
subprocess it starts, cancellation included.

### A dedicated cancellation-polling endpoint instead of extending lease renewal

Rejected.

Would introduce a second thing running on its own interval alongside
lease renewal, doubling the number of background network calls a
worker makes per running job for no real gain, when a channel that
already fires on exactly the cadence needed already exists. Matches
the same reasoning ADR 0019 used against push delivery for job
assignment.

### A side flag (cancellation_requested_at) instead of a new CANCELLING status

Rejected, deliberately, as the explicit choice made for this ADR.

Would be a smaller change to `JobStatus`, but would make a job
mid-cancellation indistinguishable from a normally running one to
anything reading `status` alone, including the dashboard. This
codebase already prefers explicit, observable states over side
channels (see `timed_out` on `JobExecutionResult`, or the reasoning
in ADR 0016's job lifecycle), and this decision follows that
precedent rather than departing from it.
