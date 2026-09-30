# ADR 0053: Fence Offline-Node Lease Delete by Lease Validity

## Status

Accepted

## Context

ADR 0052 fixed a race in `RecoverExpiredLeaseService`: it checked
lease expiry against a stale snapshot, then deleted the lease
unconditionally later in the same pass, letting a lease renewed in
between be deleted out from under its legitimate owner. That ADR
deliberately did not touch `RecoverOfflineNodeService`, since it
keys off `node.is_alive()`, not lease expiry at all, and whether an
offline node implies its worker's lease cannot still be renewing was
an open question, tracked as issue #267 rather than assumed either
way.

Tracing the actual renewal and heartbeat code paths answered that
question. In `WorkerExecutionLoop`, lease renewal runs on its own
dedicated background thread (`keep_lease_alive`), independent of any
heartbeat mechanism; the loop never calls a node-heartbeat service at
all. In the standalone agent (`scripts/run_agent.py`), heartbeating
and lease renewal run on two separate threads (`heartbeat_thread`
and `renewal_thread`), and a heartbeat failure is caught and only
printed, never propagated to the renewal thread. Node heartbeats
(`HeartbeatNodeService`) touch only `NodeRepository`, nothing about
leases.

This confirms node liveness and lease renewal are structurally
independent signals with no coupling between them. A node can be
judged offline on one missed or delayed heartbeat call while that
exact worker's lease-renewal thread, running on its own schedule,
keeps succeeding. `RecoverOfflineNodeService.execute()` never looked
up the job's lease at all: any job on a worker whose node was judged
offline was reclaimed unconditionally, regardless of whether that
worker's lease was still perfectly valid.

## Decision

`RecoverOfflineNodeService.execute()` now looks up the job's lease
via `LeaseRepository.get_by_job_id()` before deciding what to do:

- No lease exists: proceed exactly as before, nothing to protect.
- Lease exists and is expired: delete it via
  `LeaseRepository.delete_if_expired()` (added in ADR 0052), then
  reclaim the job as before, passing `lease_already_deleted=True`
  to `reclaim_job()`.
- Lease exists and is not expired: skip this job entirely. The
  worker is not marked recovered, and the job is left untouched,
  since it may still be legitimately executing despite its node's
  heartbeat having lapsed.
- Lease exists, appeared expired at the first check, but
  `delete_if_expired()` still returns `False`: the same race
  ADR 0052 closed, caught here at the last possible moment. Skip
  the same way.

## Alternatives Considered

### Trust node liveness as authoritative and leave this unchanged

Rejected once the renewal and heartbeat code paths were actually
read. Node liveness and lease renewal are not the same signal in
this codebase, so treating node offline as sufficient proof of
abandonment is not a safe assumption, it is an untested one. ADR
0052 correctly declined to assume it either way rather than guess;
this ADR replaces the guess with evidence.

### Require heartbeat and lease renewal to share a single thread or timer

Rejected as a larger change than this problem needs. Coupling them
would mean a single failure mode for both signals, which has its own
trade-offs (a slow heartbeat call would now also delay lease
renewal, for instance) and touches both `WorkerExecutionLoop` and
the standalone agent's core loop structure. Checking lease validity
independently in `RecoverOfflineNodeService`, the same way ADR 0052
already does in `RecoverExpiredLeaseService`, closes the actual race
without redesigning how workers heartbeat or renew.

## Consequences

### Positive

- The race named in issue #267 is closed and proven closed: a
  still-valid lease on an offline node's worker now survives
  reconciliation, verified with a dedicated test that constructs
  exactly that scenario.
- Both reconciliation recovery services (`RecoverExpiredLeaseService`
  and `RecoverOfflineNodeService`) now apply the same lease-validity
  fencing discipline, closing the gap ADR 0052 explicitly left open.
- No new repository method needed; `delete_if_expired()` from ADR
  0052 is reused as-is.

### Negative

- A worker on a genuinely offline node, whose lease happens to still
  be valid at the moment reconciliation runs, is left BUSY and its
  job left RUNNING rather than immediately recovered. If the node
  truly is gone and the lease's own expiry has not yet been reached,
  recovery for that job is deferred to `RecoverExpiredLeaseService`
  on a later reconciliation pass, once the lease actually expires,
  rather than happening immediately via the offline-node path. This
  is the correct trade-off: reclaiming early risks stealing a live
  lease; waiting for genuine expiry does not.
- `RecoverOfflineNodeService.execute()` now performs one additional
  repository read (`get_by_job_id`) per job on an offline node's
  worker, beyond what it did before.
