# ADR 0007: Worker Job Lease Ownership Model

## Status

Accepted

## Context

AetherGrid schedules distributed AI workloads across compute nodes and workers.

A scheduled job requires an execution owner. Without an ownership mechanism, multiple workers could accidentally execute the same job, especially during retries, worker reconnects, network failures, or scheduler retries.

A simple assignment relationship between jobs and workers is insufficient because worker availability is dynamic and execution ownership must expire when a worker becomes unhealthy.

## Decision

AetherGrid uses a lease-based ownership model for worker job execution.

When a worker accepts a job:

1. A lease is created linking:
   - worker identity
   - job identity
   - acquisition timestamp
   - expiration timestamp

2. The worker becomes the temporary owner of the job.

3. The lease can be renewed while the worker remains healthy.

4. Expired leases indicate that ownership has been lost and recovery workflows may reclaim the job.

## Consequences

### Positive

- Prevents duplicate job execution.
- Supports distributed worker failures.
- Enables future retry and recovery workflows.
- Allows workers to reconnect without permanently owning jobs.
- Provides a foundation for fault-tolerant execution.

### Negative

- Adds lifecycle complexity.
- Requires lease expiration monitoring.
- Requires recovery logic for abandoned jobs.

## Alternatives Considered

### Permanent Worker Assignment

Rejected.

A worker could disappear while still owning a job, leaving the workload permanently stuck.

### Database Row Locking Only

Rejected.

Database locks solve short-lived concurrency conflicts but do not represent ownership across distributed worker processes.

### No Ownership Tracking

Rejected.

Allows duplicate execution and makes failure recovery unreliable.

## Implementation Notes

Current implementation introduces:

- Lease domain entity
- Lease repository abstraction
- In-memory lease persistence
- Lease acquisition application service

Future work:

- PostgreSQL lease persistence
- Lease renewal heartbeat flow
- Expired lease reclamation service
