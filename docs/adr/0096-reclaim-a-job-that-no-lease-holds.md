# ADR 0096: Reclaim a Job That No Lease Holds

## Status

Accepted.

Related: ADR 0007, ADR 0011, ADR 0034, ADR 0052, ADR 0075, ADR 0078 and
ADR 0092.

## Context

ADR 0007 gives reconciliation the job of preventing permanently stuck
jobs. Two of its three recovery paths start from a lease row. The third
starts from a node that stopped sending heartbeats.

RecoverExpiredLeaseService deletes the expired lease first, with
delete_if_expired (ADR 0034, ADR 0052), and then reads the worker, the job
and the node and saves each of them in a write of its own. There is no
transaction around the four writes. When a write fails, or the process ends,
after the lease row is gone and before the job is saved, the job stays
SCHEDULED, RUNNING or CANCELLING and no lease row points at it.

No pass reaches that job again:

- RecoverExpiredLeaseService lists leases, and this one is deleted.
- SchedulerLoopService reads QUEUED jobs only.
- RecoverOfflineNodeService reads the jobs of workers on a node that stopped
  sending heartbeats. A job on a healthy node is not read. The worker was
  already reset to IDLE before the job save, so there is no worker to read
  it through either.

The job stays RUNNING, its node keeps the capacity allocated, and the job
never reaches a terminal state. The comments in AssignWorkerService (ADR
0075) already name this state as one that no recovery path reaches.

## Decision

1. RecoverLeaselessJobService starts from the jobs. It reads every lease and
   every job once per pass. A job that is SCHEDULED, RUNNING or CANCELLING and
   has no lease row is a suspect.
2. A suspect is reclaimed only when it is a suspect in two passes in a row.
   Reporting an outcome releases the lease before it saves the job, and the
   scheduler saves a job as SCHEDULED before its lease is acquired. A job
   read inside either window has no lease for a moment and is not abandoned.
   Each window closes within one request, and neither survives to the next
   pass.
3. Before the reclaim the job and its lease are read again. A job that left
   the three states, or whose lease came back, is left alone.
4. The reclaim goes through reclaim_job, the path every other recovery uses.
   It consumes a retry, fails the job once retries are exhausted, finalizes a
   CANCELLING job as CANCELLED, and releases the node after the job is saved
   (ADR 0092). The event is JobReclaimed, or JobCancelled for a job that was
   CANCELLING.
5. A worker that still holds the job as its running job is reset to IDLE.
   Other workers are not touched.
6. The service runs last in ReconciliationLoop, after the three existing
   steps, so it only sees what they left behind.
7. A job that cannot be reclaimed is logged and does not stop the other
   jobs. It stays a suspect and is tried on the next pass.
8. ReconciliationLoop runs each step on its own. A step that raises is
   logged, and the steps after it still run. Without this, a step that fails
   would stop offline-node recovery and this service for that pass.

## Consequences

- A job stranded by a failed write after the lease delete returns to the
  queue, or fails once retries are exhausted, one pass after the first pass
  that sees it without a lease, and its node gets the capacity back.
- A pass reads every lease, every job and every worker of the fleet, as the
  scheduler loop and the cluster tick already do each tick. The three reads
  are added to the list of fleet-wide readers pinned by
  test_across_tenants_callers.py. Reading only the jobs that are in the three
  states would need a repository query that does not exist yet.
- A reclaim consumes a retry, as every other reclaim does.
- A job whose lease never comes back is reclaimed even when its worker is
  alive and still running the command. Without a lease the worker is not the
  owner, and its next renewal or outcome report fails the lease check (ADR
  0036, ADR 0038), as it does after any other reclaim.

## Not Claimed

- That the writes of a recovery are atomic. They are not, and this repairs
  the state a partial recovery leaves. It does not remove the window.
- That the crash between the job save and the node save in reclaim_job is
  repaired (ADR 0092). A node's capacity is still not derived from its jobs.
- That a job is reclaimed in the first pass that sees it without a lease. It
  takes two sightings, so the tick interval passes in between.
- That the suspects survive a restart. They are held in memory. A process
  that restarts, or a new scheduler leader (ADR 0078), starts the count
  again and costs one more pass.
- That two processes running reconciliation at once are safe. Leadership (ADR
  0078) narrows that to a failover, and the repository writes are not
  conditional on the state that was read.
- That the lease clock is shared. Expiry is still judged on each process's own
  clock.
- That the state was reproduced on a process crash. The tests inject a failed
  job save after the lease delete, on the in-memory repositories made to hand
  out copies and on Postgres.

## Alternatives Considered

- **Make the recovery one transaction.** The right long-term shape, and
  rejected for this change. The services work through repository interfaces
  that each take a connection from the pool, so one transaction needs a unit
  of work across all four repositories and every recovery path. That is a
  larger change than the problem needs now, and it would still leave jobs
  already stranded in existing databases, which this repairs.
- **Reclaim at the first sighting.** Rejected. It can requeue a job in the
  window between the release of its lease and the save of its outcome, and a
  second run of a job that completed is the incident this system exists to
  prevent.
- **Compare timestamps instead of counting passes.** Rejected. A job has no
  timestamp for its last state change, and the lease that would date the
  window is the row that is missing.
- **Delete the lease last.** Rejected. It reopens the race ADR 0034 and ADR
  0052 closed, where a renewal lands after the decision to reclaim.
