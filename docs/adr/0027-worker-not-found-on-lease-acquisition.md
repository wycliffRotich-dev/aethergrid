# ADR 0027: Surface Worker Deletion as WorkerNotFoundError During Lease Acquisition

## Status

Accepted

## Context

`AssignWorkerService.execute()` reads candidate workers via `WorkerRepository.list()`, selects the first idle worker on the job's assigned node, and calls `AcquireLeaseService.execute()` to create a lease for it. Between that read and the lease insert, nothing re-validates the worker still exists.

`workers.node_id` is declared `REFERENCES nodes(id) ON DELETE CASCADE`, and `leases.worker_id` is declared `REFERENCES workers(id) ON DELETE CASCADE`. `RemoveOfflineNodeService` deletes a node once `node.is_alive()` is false, which cascades and deletes every worker on that node. If this runs concurrently with a scheduler tick that already selected one of those workers as a candidate, the lease insert in `PostgresLeaseRepository.save()` fails with `psycopg.errors.ForeignKeyViolation` on `leases_worker_id_fkey`.

This surfaced in production logs as an unhandled exception inside `_run_cluster_loop`, which aborted the entire cluster tick, not just the one affected job assignment, and only recovered because the process was restarted. Every other job scheduled in that same tick was also abandoned, not just the one that hit the race.

This is the same class of problem ADR 0011 addresses for lease expiry and node offline reconciliation: infrastructure can change out from under an in-flight operation between a read and a later write, and the system needs to treat that as an expected, recoverable outcome rather than an unhandled failure. `RenewLeaseService` already documents an equivalent race for lease renewal (the lease row being reclaimed by reconciliation between lookup and renew) and lets the repository raise a typed `LeaseNotFoundError` for it. No equivalent existed for a worker disappearing between being read as an assignment candidate and being used to acquire a lease.

## Decision

- `PostgresLeaseRepository.save()` catches `psycopg.errors.ForeignKeyViolation`, inspects `exc.diag.constraint_name`, and raises the existing `WorkerNotFoundError` when the violated constraint is `leases_worker_id_fkey`. Any other constraint violation is re-raised unchanged; this repository does not attempt to interpret failures on `job_id`, which is a materially different problem, elsewhere in the codebase a job is always persisted before a lease is acquired within the same call path.
- `AssignWorkerService.execute()` catches `WorkerNotFoundError` around the call to `AcquireLeaseService.execute()` and re-raises it as `NoAvailableNodeError`. From the scheduler's perspective, a worker that vanished mid-assignment is indistinguishable from a worker that was never available in the first place.
- No change was needed in `SchedulerLoopService`. It already catches `NoAvailableNodeError` from `AssignWorkerService` (unscheduling the job, releasing the node's reserved capacity, and leaving the job to be retried on the next tick), a path that predates this ADR and was originally written to handle an agent that hadn't finished starting up. Reusing it here means this failure mode is handled by an existing, already-tested recovery path rather than a new one.

## Rejected Alternative

Preventing the race outright, by making worker selection and lease acquisition a single atomic operation (e.g. `SELECT ... FOR UPDATE SKIP LOCKED` across one shared transaction, or an optimistic `version` column on `workers` checked at claim time). Both are viable and would close the race rather than only bound its blast radius.

Both were rejected for now because they require a structural change this codebase does not currently have: `AssignWorkerService` and `AcquireLeaseService` each operate through their own repository, each opening its own pooled connection, with no shared transaction or unit-of-work spanning the two. Introducing one is a legitimate future direction, not a one-file fix, and is not yet justified by actual worker churn. This system does not yet run under conditions (aggressive autoscaling, frequent spot instance turnover) where this race would fire often enough to matter for throughput rather than correctness.

## Consequences

A worker deleted between being selected as a candidate and being used to acquire a lease no longer crashes the cluster tick. The affected job is unscheduled and retried on the next tick, exactly as it already is when no worker was available at all. Every other job scheduled in the same tick is no longer collaterally abandoned by one unrelated race.

The underlying race itself, concurrent mutation of shared worker state between a read and a later dependent write, is not eliminated, only made safe. If worker churn increases enough that this fires frequently under real load, the two rejected alternatives above are the documented next step, most likely the optimistic `version` column, since it does not require introducing a shared transaction scope across repositories the way `SELECT ... FOR UPDATE` would.
