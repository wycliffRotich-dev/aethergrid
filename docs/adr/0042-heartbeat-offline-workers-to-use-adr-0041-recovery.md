# ADR 0042: Heartbeat OFFLINE Workers Too, So ADR 0041's Recovery Path Is Actually Reachable

## Status

Accepted

## Context

ADR 0041 made `Worker.heartbeat()` recover an OFFLINE worker to IDLE
when it holds no `running_job`, closing a real gap where an idle
worker that missed its heartbeat window had no way back without
manual re-registration.

That fix is unreachable from the dashboard's own heartbeat keeper.
`useWorkerHeartbeatKeeper` filtered its worker list to
`worker.status !== "OFFLINE"` before sending heartbeats, on the
reasoning (correct at the time it was written, before ADR 0041
existed) that heartbeating an already-OFFLINE worker did nothing
useful. Once a worker flips OFFLINE for any reason while the tab
stays open, the hook stops heartbeating it permanently. Nothing else
in the frontend heartbeats a worker by id, so that worker has no path
back to IDLE for the rest of the session, exactly the situation ADR
0041 exists to fix, made unreachable by the one caller that runs on
every page load.

Observed live: a worker went OFFLINE not from a stale heartbeat
timeout, but from ordinary job-cancellation activity, its lease was
released and status set to IDLE directly by
`Worker.cancel_job()`/`ReportJobOutcomeService`, neither of which
touches `last_seen_at`. Enough wall-clock time had separately elapsed
since this worker's last real heartbeat that `MarkDeadWorkersService`
marked it OFFLINE on its next reconciliation pass. From that point,
the keeper's filter excluded it from every future heartbeat cycle,
permanently, until the page was reloaded or the worker was manually
re-registered.

## Decision

`useWorkerHeartbeatKeeper` now heartbeats every worker, OFFLINE ones
included, not just ones already considered alive. This is safe by
construction: ADR 0041 already restricts recovery to the case where
`running_job is None`, so heartbeating an OFFLINE worker that still
holds a job (the case reconciliation, not a bare heartbeat, must
resolve) has no effect, it stays OFFLINE exactly as ADR 0041 intends.

Nodes are untouched by this change. The node-side filter
(`node.is_alive`) stays as-is; this decision is scoped to worker
liveness only, since node recovery-on-heartbeat was never part of
ADR 0041's scope and introducing it here would be an undiscussed
scope expansion, not a fix.

## Consequences

An idle worker that goes OFFLINE while the dashboard tab remains open
now recovers on this hook's very next 20-second heartbeat cycle,
rather than requiring a page reload or manual re-registration to
reach ADR 0041's recovery path at all.

This makes ADR 0041 and this ADR a single, load-bearing pair:
ADR 0041 defines when a heartbeat is allowed to recover a worker,
ADR 0042 ensures a heartbeat is actually sent to a worker that needs
recovering. Neither is sufficient alone; together they close the gap
completely for the dashboard's own heartbeat-keeper stand-in
(documented in `useWorkerHeartbeatKeeper`'s own comment as exactly
that, a stand-in for a real agent process, not a production liveness
mechanism).

This does not change `MarkDeadWorkersService`'s behavior, a worker
still goes OFFLINE exactly as before, after `HEARTBEAT_TIMEOUT`
lapses with no heartbeat received, from any cause. It only ensures
the mechanism responsible for sending heartbeats does not exclude
the workers most in need of one.
