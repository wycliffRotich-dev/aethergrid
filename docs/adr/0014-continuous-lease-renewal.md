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

## Progress

2026-11-22. Two flaws in how WorkerExecutionLoop handles a lost lease were found and fixed. The Decision above says the loop treats LeaseNotFoundError from the renewal thread as the loss of ownership. That covered a lease replaced by another one. It did not cover a worker that holds no lease at all, which is what reconciliation leaves behind when it reclaims a job, and RenewLeaseService raises NoActiveLeaseError in that case. The renewal thread did not catch it, so the thread ended with an unhandled error and the loop never learned of the loss. The loop also recorded the outcome event, and moved the worker and the job to their final states, before it released the lease. A release that refused therefore came too late: JobCompleted was already recorded and the worker was already idle.

The thread now catches both errors, records the loss and stops after the first refusal. The loop raises that error without calling the release. The release now runs before the outcome is decided, so it is the fence. If the lease is gone or replaced, the release raises before the worker or the job changes state and before any outcome event exists. The worker, node and job saves come next, and the outcome event is written after them. With a recorder on the release service, a normal run records LeaseReleased first and the outcome event after it.

Eight cases in tests/application/workers/test_worker_execution_loop_lost_lease.py pin this: a reclaimed lease and a replaced lease seen by the renewal thread, a lease lost after the last renewal, the thread ending without an unhandled error for each of the two refusals, the thread stopping after the first refusal, the outcome event coming after the saves, and the release event coming before the outcome event. Of the first three, the reclaimed lease and the late loss failed before the change, and both ended with JobCompleted recorded. Eleven deliberate breaks each turned tests red, and only the tests that pin what was changed: the renewal thread catching only LeaseNotFoundError (1 case), catching only NoActiveLeaseError (1), not stopping after a lost lease (1); the raise of the lost lease removed (2); the release put back after the worker and job transitions (1); the outcome event written before the saves (1); the outcome event dropped (5); the cancelled outcome recording JobFailed (1); the completed outcome recording JobFailed (1); the failed outcome recording JobCompleted (2); the release moved behind the event write (2). Each time the file was restored and its hash compared.

Not claimed: safe to expose.
