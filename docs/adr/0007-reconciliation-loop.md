# ADR-0007: Reconciliation Loop

## Status

Accepted

## Context

Worker execution and lease ownership guarantee that jobs are processed by
a single worker. However, failures can still occur outside the normal
execution path.

Examples include:

- a worker crashes after acquiring a lease
- a process terminates unexpectedly
- a lease expires before completion
- inconsistent state caused by infrastructure failures

These situations can leave workers, leases, and jobs out of sync.

The platform therefore requires a background reconciliation process that
continuously repairs inconsistent state without operator intervention.

## Decision

AetherGrid introduces a dedicated Reconciliation Loop.

The reconciliation loop periodically scans the system and compares the
state of:

- Workers
- Jobs
- Leases

Whenever an inconsistency is detected, deterministic repair logic restores
the correct state.

Typical repairs include:

- releasing orphaned leases
- resetting workers that no longer own jobs
- returning abandoned jobs to the queue
- cleaning invalid ownership relationships

The reconciliation loop operates independently of worker execution and
scheduling.

## Consequences

### Advantages

- Automatic recovery from crashes.
- Self-healing infrastructure.
- Prevents permanently stuck jobs.
- Keeps domain invariants consistent.
- Simplifies operational maintenance.

### Trade-offs

- Introduces an additional background service.
- Requires careful repair rules to avoid conflicting with active workers.
- Periodic scans add a small operational overhead.

### Incremental Evolution

The reconciliation loop is intentionally introduced as a minimal controller.

Rather than implementing every recovery strategy immediately, each
reconciliation behaviour will be added independently using test-driven
development.

Every new repair rule represents a separate architectural decision and
must be validated in isolation before becoming part of the controller.

Examples include:

- releasing orphaned leases
- recovering abandoned jobs
- resetting inconsistent worker state
- repairing expired ownership relationships

This approach keeps the controller cohesive, simplifies reasoning about
individual recovery mechanisms, and reduces the risk of introducing
unintended interactions between unrelated repair strategies.

## Alternatives Considered

### Manual recovery

Rejected because it does not scale and increases operational burden.

### Event-driven recovery only

Rejected because some failures produce no events, making periodic
reconciliation necessary.
