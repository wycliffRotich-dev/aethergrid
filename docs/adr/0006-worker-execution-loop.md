# ADR-0006: Introduce Worker Execution Loop

## Status

Accepted

## Context

AetherGrid schedules jobs onto compute nodes and assigns them to workers
through a lease. Once a worker has accepted a job, the platform must
ensure that execution follows a consistent lifecycle while maintaining
lease ownership.

Initially, job execution and lease release both attempted to complete
the worker, resulting in duplicated business logic. The domain state
machine rejected this behaviour because it attempted an invalid
transition directly from `SCHEDULED` to `COMPLETED`.

The execution flow required a single component responsible for driving
the worker lifecycle.

## Decision

Introduce a dedicated `WorkerExecutionLoop` application service.

The execution loop is responsible for:

1. Loading the worker.
2. Verifying that the worker has an assigned job.
3. Renewing the worker's lease.
4. Starting execution of the assigned job.
5. Delegating completion to `ReleaseLeaseService`.

`ReleaseLeaseService` becomes responsible for:

- completing the worker
- releasing the worker's lease
- persisting the updated worker state

The `Worker` aggregate remains the only component permitted to perform
job state transitions.

## Consequences

### Positive

- Clearly separates execution from lease management.
- Eliminates duplicated completion logic.
- Preserves the integrity of the job state machine.
- Makes future retry and failure handling easier to implement.
- Keeps orchestration logic within the application layer.

### Negative

The current implementation assumes successful execution.

Future enhancements should introduce:

- execution failures
- retries
- cancellation
- execution timeouts
- worker crashes during execution

## Alternatives Considered

### Complete the worker inside WorkerExecutionLoop

Rejected because lease management would still need to determine whether
execution had finished, resulting in duplicated business logic.

### Complete the worker inside ReleaseLeaseService

Accepted because lease release naturally represents the end of a worker's
ownership of a job, making it the appropriate place to finalize execution.

## Related ADRs

- ADR-0004: Worker Registration API
- ADR-0005: Worker Job Lease Ownership
