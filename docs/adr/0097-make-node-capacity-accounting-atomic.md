# ADR 0097: Make Node Capacity Accounting Atomic

## Status

Proposed.

Related: ADR 0064, ADR 0092 and ADR 0093.

## Context

The scheduler, outcome reporting, the worker loop and reclaim_job each
read a node, change its available figures and save the whole row. Two of
them acting on one node at the same time can overwrite each other. ADR
0092 and ADR 0093 both name this. ADR 0093 fixed the heartbeat by writing
only the heartbeat time, and left the remaining writers open.

The dangerous direction is allocation. The scheduler reads a snapshot of
available nodes, picks one, subtracts the job's resources in memory and
saves the whole row. Two writers can both read the same available figures
and both save, over-committing the node. The advisory lock (ADR 0078)
narrows this to a failover window but does not close it.

ADR 0093's Alternatives Considered named the fix: make every node write
a delta. It was deferred for its own ADR, which this is.

## Decision

1. NodeRepository gains allocate(node_id, tenant_id, requirements). It
   subtracts the requirements from available in one conditional update,
   which applies only when every requested dimension is still available.
   It returns True when the allocation applied, and False otherwise.
2. NodeRepository gains release(node_id, tenant_id, requirements). It
   adds the requirements back in one update, capped at the node's total
   capacity. It returns True when the release applied, and False
   otherwise.
3. A node in another tenant, or no node at all, returns False and leaves
   the row untouched, matching record_heartbeat and every other scoped
   method.
4. The scheduler allocates through the repository method and, when it
   returns False, leaves the job QUEUED for the next tick instead of
   overwriting a stale available figure. Outcome reporting, the worker
   loop and reclaim_job release through the repository method.
5. All three backends implement both methods, and the shared contract
   tests them on each.

## Consequences

- Two writers can no longer over-commit a node: the conditional update
  fails when the capacity is gone.
- A release is a single atomic add, capped at capacity, so it cannot
  write a stale figure over a concurrent allocation.
- The scheduler may skip a job this tick when its chosen node was
  allocated between the snapshot and the update. The job stays QUEUED
  and is re-selected next tick, the same retry shape already used for a
  missing worker.

## Not Claimed

- That the domain Node.allocate and Node.release methods are removed.
  They remain for the domain layer and its tests; the application no
  longer uses them for persistence.
- That two schedulers can never schedule the same job. The unique lease
  constraints remain the backstop for job ownership; this ADR closes the
  capacity over-commit only.

## Alternatives Considered

- **Keep the read, change and save, and add a version check.** Rejected.
  A version check turns a lost update into a retry; the delta update
  removes the lost update and reads nothing first.
- **Derive a node's available capacity from its assigned jobs.** Not
  rejected, only deferred. It is a larger change and does not by itself
  make the individual write atomic.

## How to Verify

```bash
pytest -q tests/infrastructure/repositories -k "allocate or release"
```

All of them pass.

## Progress

2026-11-16. The contract tests for allocate and release were written to
specify the two deltas. The scheduler's allocate was then changed to use
the repository method, and outcome reporting, the worker loop and
reclaim_job now release through it. The in-memory and SQLite node
contract tests pass (54 tests), the Postgres node contract and heartbeat
tests pass (28 tests), the scheduler, outcome, worker-loop and reclaim
suites pass (67 tests), and the full suite passes against Postgres
(1411 passed, 2 skipped). ruff and mypy are clean.
