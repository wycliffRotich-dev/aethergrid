# ADR 0030: Idempotent Worker Registration Per Node

## Status

Proposed

## Context

`scripts/run_agent.py` registers a new `Worker` every time it
starts, via `POST /workers` -> `CreateWorkerService.execute()` ->
`RegisterWorkerService.execute()`. Neither service checks whether
a worker already exists for the given `node_id` before creating
one. `WorkerId.new()` mints a fresh UUID unconditionally.

This was never a problem with a single node and a single
long-lived agent process. It becomes one the moment an agent
restarts against a node it has already registered a worker for,
which is not a rare event at fleet scale: a crash, a redeploy, a
machine reboot, or simply `Ctrl+C` followed by starting the
script again all produce the same outcome, a second `Worker` row
pointed at the same `Node`.

The old row does not disappear. `MarkDeadWorkersService` only
ever calls `worker.offline()` once its heartbeat lapses; nothing
in this codebase calls `WorkerRepository.delete()` on a worker
that is merely offline, only `RemoveOfflineNodeService`'s cascade
does that, and only for the node itself, not for an individual
stale worker under a node that is still alive. `AssignWorkerService`
tolerates this correctly today, since it filters on `is_idle()`
before matching a node, but tolerating a growing pile of dead
rows is not the same as the system's data model being accurate.

Every place that lists workers, `ListWorkersService`,
`WorkerTable.tsx`, has no way to distinguish "this node has
restarted its agent five times" from "this node genuinely has
five workers." At single-node scale this is invisible. At fleet
scale, with dozens of nodes each restarting on their own
schedule, the worker table stops describing the cluster's actual
shape.

The root problem is that `Worker` identity is currently
independent of `Node` identity, when in practice the domain
already treats them as 1:1 everywhere else: `AssignWorkerService`
matches a job's `assigned_node_id` against `worker.node.id`
expecting to find the worker for that node, not a worker among
several. The data model has just never enforced the constraint
the rest of the code already assumes.

## Decision

A worker's identity is keyed to its node. Registering a worker
for a node that already has one reclaims the existing `Worker`
rather than creating a new one.

`WorkerRepository` gains one new method:

```python
@abstractmethod
def get_by_node_id(
    self,
    node_id: NodeId,
) -> Worker | None:
    """
    Retrieve the worker registered for a node, if one
    exists.
    """
```

`RegisterWorkerService` (or a service composing it, exact
placement decided during implementation) looks up the existing
worker for the target node first:

```python
existing = self._worker_repository.get_by_node_id(node.id)

if existing is not None:
    existing.recover()
    existing.managed_by = managed_by
    existing.ready()
    self._worker_repository.save(existing)
    return existing

worker = Worker(id=WorkerId.new(), node=node, managed_by=managed_by)
worker.ready()
self._worker_repository.save(worker)
return worker
```

Reclaiming calls `Worker.recover()`, the same method
reconciliation already uses for abandoned work: any
`running_job` is forgotten and the worker returns to `IDLE`. An
agent that crashed mid-job and restarted has no way to know what
that job's true outcome was, so the existing recovery semantics
apply unchanged, this is not a new rule, it is the existing rule
applied at the point an agent comes back rather than only when
`MarkDeadWorkersService` notices it left.

`WorkerId` does not change on reclaim. The worker a job's
`assigned_node_id` was matched against, and any external system
that has recorded that worker's id, keeps referring to the same
identity across the agent's restart.

## Rationale

The domain already behaves as though a node has exactly one
worker; this decision makes the data model say what the code
already assumes, instead of leaving the two to quietly disagree
at scale.

Recovery on reclaim is not new behavior invented for this
decision, it is `Worker.recover()`, the same method that already
exists for exactly this situation, applied one call site earlier.

Keeping the same `WorkerId` across a restart is what makes this
idempotent rather than merely tidier: calling `POST /workers`
against the same node any number of times converges on one
worker, not on progressively fewer duplicates.

## Consequences

### Positive

- One node maps to exactly one worker, for the life of that
  node, matching what `AssignWorkerService` and the dashboard
  already assume.
- Agent restarts, which are routine at fleet scale, no longer
  leave permanent dead rows behind.
- `MarkDeadWorkersService` marking a worker `OFFLINE` becomes
  genuinely transient again: the same node's next agent start
  reclaims that exact row instead of abandoning it next to a
  new one.
- No new failure mode: reclaim reuses `Worker.recover()`,
  behavior already exercised by reconciliation and already
  under test.
- Idempotent by construction: registering against the same node
  any number of times converges on one worker.

### Negative

- `WorkerRepository` gains a method every implementation must
  support; all three repositories (postgres, sqlite, in-memory)
  and the shared contract test suite need updating in the same
  change.
- A worker id can now outlive several distinct agent processes.
  Anything that assumed a `WorkerId` maps to one continuously
  running process instance, rather than one node over time, no
  longer holds. Nothing in the current codebase depends on that
  assumption, but it is a real change to what the identifier
  means.
- Reclaiming silently discards whatever the previous agent
  process's `running_job` was, exactly as `recover()` already
  does for reconciliation. This is an accepted, pre-existing
  tradeoff, not a new one, but it now also applies at agent
  startup, not only when the dead-worker sweep notices a lapsed
  heartbeat.

## Alternatives Considered

### Alternative A -- Reject re-registration (409 Conflict)

Rejected.

Would require an operator to manually delete the stale worker
before an agent could restart, defeating the purpose of an
unattended agent recovering from a crash or redeploy. Fleet-scale
operation depends on agents being able to come back on their own.

### Alternative B -- Leave registration as-is, clean up separately

Rejected.

Would mean adding a periodic sweep to delete `OFFLINE` workers
whose node still has a newer worker registered against it,
solving the symptom after the fact rather than the cause. Also
reintroduces a window, however small, where a node genuinely has
more than one worker on record, which is the exact state every
consumer of `ListWorkersService` was never designed to interpret.

### Alternative C -- Composite identity (node_id as the worker's key)

Rejected.

Would remove `WorkerId` as an independent value object entirely
and key workers directly by `NodeId`, which is simpler but a
larger change: `WorkerId` is threaded through leases, job
assignment, and every worker-scoped API route as its own typed
identifier (ADR 0004). Reusing the same `WorkerId` across
reclaims achieves the same 1:1 guarantee without touching
identity elsewhere in the system.

## Impact

This ADR affects:

- Domain
    - Worker (`recover()` now called from registration, not
      only reconciliation)

- Application
    - RegisterWorkerService / CreateWorkerService

- Infrastructure
    - WorkerRepository (new abstract method)
    - PostgresWorkerRepository, SqliteWorkerRepository (or
      InMemoryWorkerRepository, whichever backs local dev),
      InMemoryWorkerRepository

- Tests
    - worker_repository_contract.py (new shared contract test)
    - Worker registration tests

## Compliance

This decision aligns with the architectural principles adopted by
AetherGrid:

- Domain-Driven Design (DDD)
- Rich Domain Model
- Repository Pattern
- Idempotency at system boundaries
- Infrastructure Independence

## References

- ADR 0004: Worker Registration API
- ADR 0019: Standalone Worker Agent Process
