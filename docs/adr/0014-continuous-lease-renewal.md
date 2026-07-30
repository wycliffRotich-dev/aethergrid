# ADR 0014: Continuous Lease Renewal and Strict Renewal Semantics

## Status

Accepted

## Context

`WorkerExecutionLoop` renewed a worker's lease exactly once, immediately before calling `JobExecutionService.execute()`. That call is a single blocking `subprocess.communicate(timeout=...)`, and `job.execution_timeout` is caller-defined per job. `DEFAULT_LEASE_DURATION` is 30 seconds. Any job configured to run longer than that, which is the entire reason a configurable timeout exists, had its lease expire while the worker was still correctly executing it. No stall, no crash, no unusual timing required. An ordinary 45-second job was enough.

Once that lease expired, the reconciliation loop would reclaim the job on its next cycle and requeue it. A second worker could then pick it up and execute it concurrently with the first, which was still running, unaware anything had changed. Both workers would eventually try to persist a result for the same job.

Fixing the renewal cadence alone was not sufficient. `RenewLeaseService` renewed by reading the current lease, calling `lease.renew()`, and writing it back through `LeaseRepository.save()`, which is an upsert (`INSERT ... ON CONFLICT (id) DO UPDATE`). If a renewal read the lease before reconciliation deleted it, then wrote after the delete, the upsert would find no conflicting row and simply insert one, resurrecting a lease that reconciliation had already reclaimed. Because `job_id` is unique on the leases table, that resurrected row would block the job from ever being reassigned, since `AcquireLeaseService` refuses to acquire a lease for a job that already appears to have one. The row would sit there looking legitimate, with a valid future `expires_at`, until someone noticed the job was permanently stuck.

Two distinct problems, one root cause: lease renewal treated "extend an existing lease" and "create a lease" as the same operation.

## Decision

- `WorkerExecutionLoop` renews on a background thread for the entire lifetime of job execution, at an interval of one third of `DEFAULT_LEASE_DURATION`, rather than once before execution starts. The thread is stopped and joined in a `finally` block once the subprocess call returns, so it never outlives the job it exists to protect.
- `LeaseRepository` gains a `renew(lease_id, duration)` method, distinct from `save()`. `renew()` is implemented as a conditional update, an `UPDATE ... WHERE id = ...` in Postgres, an equivalent existence check in the in-memory repository, and it raises `LeaseNotFoundError` when no matching row exists. It never creates a row under any circumstance.
- `save()` is unchanged and remains the acquire-time path used by `AcquireLeaseService`, where creating a new lease is exactly the intended behavior.
- `RenewLeaseService` calls `renew()` instead of the previous read-mutate-save sequence.
- `WorkerExecutionLoop` treats `LeaseNotFoundError` from the renewal thread as an authoritative signal that ownership of the job has been lost. When it fires, the execution result is discarded rather than persisted. The subprocess may have completed successfully, but this worker no longer has standing to record that outcome as canonical.
- The shared `LeaseRepositoryContract` gains tests covering successful renewal and, specifically, renewal attempted after the lease has already been deleted, which must raise rather than recreate the row.

## Consequences

A job's lease now survives for as long as the job actually runs, regardless of how long that is. The 30-second default lease duration bounds how quickly a genuinely dead worker's job gets reclaimed. It no longer also bounds how long a job is allowed to take.

Renewal can now fail. It cannot succeed in a way that silently corrupts state. A worker that loses its lease finds out during renewal, not after the fact when a save collides with another worker's write.

This does not add fencing at the point `job_repository.save(job)` is called. The current design relies on renewal failure as the signal that ownership was lost, which is reliable given the fix above, but it is an inference from renewal behavior rather than an explicit check of lease identity at save time. A future change could thread the lease id through to the save call itself for a more direct guarantee. That was judged out of scope here, since the renewal-failure path already closes the specific races this ADR addresses.

Both `LeaseRepository` implementations, Postgres and in-memory, must maintain identical `renew()` semantics going forward. The contract test suite is what enforces this, not code review discipline, matching the precedent set by ADR 0010.
