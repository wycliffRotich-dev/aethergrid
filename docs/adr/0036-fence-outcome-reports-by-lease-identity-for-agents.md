# ADR 0036: Fence Standalone-Agent Outcome Reports by Lease Identity

## Status

Accepted

## Context

ADR 0034 fenced `ReleaseLeaseService` by requiring callers to state
which lease they believe they are releasing, closing a real
cross-job lease-theft path for the in-process execution loop
(`WorkerExecutionLoop`) and the outcome-reporting path
(`ReportJobOutcomeService`). That ADR named a scoped, explicit
limitation rather than claiming full coverage: `ReportJobOutcomeService`
narrows its own fencing window to a single request's handling time,
but the external HTTP contract the standalone agent (ADR 0019) uses
does not carry lease identity from the agent back to the server at
all. The agent has no way to state which lease it believes it holds
when it calls `POST /workers/{worker_id}/jobs/{job_id}/complete`,
`/fail`, or `/cancel`.

The consequence: `ReportJobOutcomeService._current_lease_id()`
fetches whatever lease is current for the worker *at the moment the
report arrives* and treats that as the value to fence against. This
protects against a report landing after the lease was released or
reassigned to a *different* worker or job, since the mismatch
between `worker.running_job.id` and the reported `job_id`, or a
missing/mismatched lease, is caught by existing checks
(`WorkerJobMismatchError`, `NoActiveLeaseError`). It does not
protect against the narrower case those checks cannot see: the
*same* worker reassigned the *same* job with a *new* lease between
when a stale agent started executing and when it finally reports.
In that case every existing check passes, because the fencing value
being compared against is itself derived from "whatever is current
right now," which can never disagree with itself. This is
tautological, not a real check, exactly as ADR 0034 already named
it.

Tracing the standalone agent's actual poll loop
(`scripts/run_agent.py`) shows the fix does not require a new
round trip. `run_job()` already receives the job it is about to
execute from `get_worker()`'s `running_job` field, before it ever
calls `start_job()`. The lease already exists by that point,
acquired when the job was assigned; the agent simply has no way to
learn its identity, since `RunningJobResponse` does not expose it.

## Decision

- `RunningJobResponse` gains a `lease_id: str | None` field, the
  identity of the lease the worker currently holds for this job,
  read via `LeaseRepository.get_by_worker_id()` wherever
  `GetWorkerResponse` is constructed. In practice, only three of
  the six response-construction sites in `app/presentation/routers/
  workers.py` can ever have a non-null value: `get_worker`,
  `start_job`, and `renew_lease`, since `complete_job`, `fail_job`,
  and `confirm_job_cancellation` all clear `worker.running_job` to
  `None` as part of their own domain transition before the response
  is built. The field stays on the one shared response shape rather
  than forking it, since `RunningJobResponse` already varies by
  content (a completed worker naturally has no `running_job` at
  all) and a sixth near-duplicate schema was judged worse than one
  nullable field.
- The six duplicated `RunningJobResponse` construction blocks in
  `workers.py` are consolidated into one shared builder function,
  since adding a new field to six independent, hand-copied blocks
  is exactly the kind of duplication this codebase avoids
  elsewhere (see `persist_job_started`, ADR 0033).
- `scripts/run_agent.py`'s `run_job()` reads `lease_id` directly
  from the `job` dict it already receives from `get_worker()`,
  stores it locally for the life of that execution, and passes it
  to `report_outcome()`.
- `ReportJobOutcomeRequest` gains a required `lease_id: UUID`
  field. This is a breaking change to the request contract; every
  caller of `complete`/`fail`/`cancel`, in practice only the
  standalone agent today, must send it or the request is rejected
  by schema validation before it ever reaches the service layer.
- `ReportJobOutcomeService.complete/fail/cancel` accept the
  caller-supplied `lease_id` as `expected_lease_id` and compare it
  against the lease actually current for the worker, the same
  fencing shape ADR 0034 already established for
  `ReleaseLeaseService`, reusing `LeaseNotFoundError` on mismatch
  rather than inventing a new exception.

## Consequences

### Positive

- Closes the specific, named gap ADR 0034 left open for the
  standalone-agent path: a stale agent reporting against a
  since-reassigned lease for the same worker and job is now
  rejected, not silently accepted.
- No new network round trip. The lease id rides an existing
  response the agent already receives before execution begins.
- Consolidating six duplicated response blocks into one builder
  removes a real maintenance hazard (a seventh field added later
  would otherwise need six synchronized edits) while making this
  change.

### Negative

- Breaking change to `ReportJobOutcomeRequest`. Any caller of the
  outcome-report endpoints that does not send `lease_id` will be
  rejected outright once this ships; the standalone agent script
  must be updated in the same change, not a follow-up.
- `lease_id` is `None` on any response where `running_job` reflects
  a job that just transitioned to a terminal state in the same
  call. Consumers must not assume a non-null `running_job` always
  carries a non-null `lease_id`.
- Does not address the in-process (`WorkerExecutionLoop`) path
  further; that path was already fully fenced by ADR 0034 using
  the lease repository directly, with no HTTP boundary to cross.
  This ADR is scoped entirely to the external agent contract.

## Alternatives Considered

### Have the agent re-fetch the current lease id just before reporting, instead of carrying it from the start-of-execution poll

Rejected.

Would defeat the purpose of fencing entirely: fetching "whatever is
current right now" immediately before comparing against "whatever
is current right now" is the same tautology this ADR exists to
close, just moved one step later. The value being fenced against
must be captured at the point the agent's belief about ownership
was actually formed, not re-derived at report time.

### Add a new, dedicated endpoint for the agent to fetch its current lease id, rather than exposing it on RunningJobResponse

Rejected.

Would add a network round trip and a new endpoint for information
the agent already receives, unused, in a response it already
fetches every poll cycle. No new failure mode or latency is
justified when the existing response already carries everything
needed.
