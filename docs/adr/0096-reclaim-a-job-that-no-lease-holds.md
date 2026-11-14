# ADR 0096: Reclaim a Job That No Lease Holds

## Status

Proposed.

Related: ADR 0007, ADR 0034, ADR 0052, ADR 0075, ADR 0078 and ADR 0092.

## Context

ADR 0007 gives reconciliation the job of preventing permanently stuck
jobs. Two of its three recovery paths start from a lease row. The third
starts from a node that stopped sending heartbeats.

RecoverExpiredLeaseService deletes the expired lease first, with
delete_if_expired (ADR 0034, ADR 0052), and then reads and saves the
worker, the job and the node, each in a write of its own and with no
transaction around them. When a write fails, or the process ends, after
the lease row is gone and before the job is saved, the job stays
SCHEDULED, RUNNING or CANCELLING with no lease row pointing at it.

No pass reaches that job again:

- RecoverExpiredLeaseService lists leases, and this one is deleted.
- SchedulerLoopService reads QUEUED jobs only.
- RecoverOfflineNodeService reads the jobs of workers on a node that
  stopped sending heartbeats. A job on a healthy node is not read, and the
  worker was already reset to IDLE before the job save, so there is no
  worker to read it through either.

The job stays RUNNING, its node keeps the capacity allocated, and the job
never reaches a terminal state. The comments in AssignWorkerService (ADR
0075) already describe this state as one no recovery path reaches.

Repairing it is harder than finding it, because an abandoned job and an
in-flight job look the same. Both are SCHEDULED, RUNNING or CANCELLING
with no lease row.

## Decision

1. **Invariant.** A job in SCHEDULED, RUNNING or CANCELLING holds a lease
   row, or is being written by an operation that is still running.
   RecoverLeaselessJobService repairs a job that has held no lease for
   longer than T and whose writer is gone.

2. **Three writers produce a leased-state job with no lease row.** Each
   one leaves the job behind if it stops partway, and each one can stall
   past T while the job is in that state.
   1. Expired-lease recovery deletes the lease, then saves the worker, the
      job and the node in separate writes.
   2. The scheduler saves the job as SCHEDULED before its lease exists
      (ADR 0075).
   3. An outcome report, through ReportJobOutcomeService or
      WorkerExecutionLoop, releases the lease, saves the worker, and then
      saves the job and the node. Decision 10 fences its job save.

3. **T is a named constant, MIN_LEASELESS_AGE_SECONDS, 180 seconds.** It
   has no exact bound, because every repository call in writers 2 and 3 can
   wait for the connection pool, up to 30 seconds each, and an operation
   makes several. T is a heuristic with a margin of six such waits, and the
   reclaim is safe when it is wrong (decision 4).

4. **The reclaim is one fenced write.** JobRepository.save_if_leaseless
   saves the job only if its stored status is one of the expected
   statuses and no lease row exists. On Postgres it locks the job row with
   FOR UPDATE, checks the status and the lease table, and writes, in one
   transaction. A lease insert takes FOR KEY SHARE on the job row through
   its foreign key. An insert already in flight when the lock is requested
   finishes first, and the lease check sees it. An insert that starts
   while the lock is held waits, and succeeds after the commit, because
   the insert does not check the job's status (see Not Claimed). The
   in-memory and SQLite backends keep leases in this process and are
   atomic only against writers in this process. A refused write changes
   nothing and credits no node.

5. **The reclaim has its own helper, reclaim_leaseless_job.** There is no
   lease to delete, so none is deleted. The helper copies the job it is
   given, reclaims the copy, fences the write on the status the job had
   when it was handed in, and returns the copy only if the write was
   accepted. The caller's object is never changed, so a refused write
   cannot leave an object behind that looks reclaimed and was never
   saved, and a caller cannot pass a status that disagrees with its job.
   reclaim_job is unchanged. Its four callers start from a lease and rely
   on its bool result and on the job being changed in place.

6. **The age is measured, not counted.** The service records, on a
   monotonic clock, when it first saw each job without a lease and in which
   status. A change of status starts the clock again. The sightings are
   cleared when a pass fails to read, and when the previous pass ended more
   than MAX_PASS_GAP_SECONDS ago, 30 seconds against a tick of one second,
   so a sighting from before a stall or a loss of leadership is never joined
   to one after it.

7. **The node is released after the job is saved (ADR 0092), in every path
   that releases it.** ReportJobOutcomeService and WorkerExecutionLoop used
   to credit the node and save it before saving the job. A crash between
   the two writes left a RUNNING job with no lease on a node that was
   already credited, and recovering that job released the same resources a
   second time. Node.release clamps at capacity, so the error stayed hidden
   on an idle node and showed as over-reported free capacity on a node with
   other jobs. Both paths now save the job first. A crash between the two
   writes under-reports free capacity, the direction ADR 0092 accepts. This
   was chosen over deriving a node's available capacity from the jobs that
   hold it. That would also close the leak ADR 0092 accepts, and it is a
   larger change that this one does not need.

8. **Failures stay inside one job.** A job that cannot be reclaimed is
   logged and does not stop the others. If the job is still without a lease
   at the next pass it is tried again. A worker is freed only after its job
   was reclaimed, and only if it is read again and still holds that job. An
   event lost after the job was saved is logged as lost and is not retried.

9. **The service runs last in ReconciliationLoop, and each step runs on its
   own.** A step that raises is logged, and the steps after it still run.

10. **An outcome is saved with the same fenced write.** From the lease
    release until the job save, a job that is reporting its outcome is
    RUNNING or CANCELLING with no lease, the state this service reclaims.
    A report that stalls longer than T there would otherwise save its
    terminal status over the requeued job, and then credit the node the
    reclaim had already credited. If the job had been assigned again, it
    would be marked finished while it runs. ReportJobOutcomeService and
    WorkerExecutionLoop therefore save the job through save_if_leaseless,
    expecting RUNNING or CANCELLING (FINISHING_STATUSES). CANCELLING is
    accepted because ADR 0029 lets a job that finishes before the
    cancellation signal reaches it end COMPLETED or FAILED, and a
    cancellation request can be saved while the report is in flight. A
    reclaim moves the job out of both statuses, to QUEUED, FAILED or
    CANCELLED. A refused write credits no node, records no event, and
    raises JobReclaimedError, which the API returns as 409, as it does for
    a lost lease.

    Worker.complete(), fail() and cancel_job() change the job in place
    before the write. On Postgres that job was read fresh with the
    worker, and the status the write expects is the one the database
    holds. The in-memory job repository hands out the object it stores,
    so the services first give the worker a copy of its job
    (take_running_job). Otherwise the stored job would show the outcome
    before it was written, and the fence would refuse it.

## Consequences

- A job stranded by a failed write returns to the queue, or fails once its
  retries are exhausted, about three minutes after it lost its lease. Its
  node is credited at most once. A crash between the job save and the node
  save in any of the three paths that release a node leaves the capacity
  allocated, which nothing repairs yet (Not Claimed).
- A worker whose outcome report arrives after its job was reclaimed gets
  409, the same answer as for a lost lease, and its outcome is dropped.
- A pass reads every lease and every job of the fleet, across tenants, and
  every worker only when a job is ready to reclaim. The reads are added to
  the list of fleet-wide readers pinned by test_across_tenants_callers.py.
  Reading only the jobs in the three states would need a repository query
  that does not exist yet.
- A reclaim consumes a retry, as every other reclaim does.
- A job whose lease never comes back is reclaimed even when its worker is
  alive and still running the command. Without a lease the worker is not
  the owner, and its next renewal or outcome report fails the lease check
  (ADR 0036, ADR 0038), as it does after any other reclaim.
- JobRepository has a new abstract method, implemented for Postgres, SQLite
  and memory. The in-memory and SQLite repositories take the lease
  repository as an optional argument, and the composition root passes it.

## Not Claimed

- That the suspects survive a restart. They are held in memory, and a
  restart or a new leader costs one more minimum age.
- That the lease clock is shared. Expiry is still judged on each process's
  own clock.
- That a lease insert is refused once the fenced write holds the row lock.
  An insert that reaches its foreign key check while the lock is held
  waits for it, and succeeds after the commit, because the job row still
  exists and the insert does not look at the job's status. A writer that
  read the job before the reclaim and stalled through it, such as a
  scheduler that saved the job as SCHEDULED and stalled for longer than T
  before acquiring its lease, can therefore leave a live lease on a job
  that is now QUEUED or terminal. The age guard makes this improbable, not
  impossible. The fix, a lease insert that locks the job row and checks
  its status in the same transaction, is tracked in #507.
- That every job writer is fenced. CancelJobService still saves
  unconditionally. A cancellation that reads a RUNNING job before an
  outcome is saved, and writes CANCELLING after it, puts the finished job
  back into CANCELLING with no lease. This service then cancels it after
  T and credits the node a second time. Before this change the same race
  left the job in CANCELLING for good. It needs the cancel request's
  read and write to straddle the whole outcome write. It is tracked in
  #507 with the lease insert.
- That capacity leaked by a crash is repaired. The node is released after
  the job is saved in three paths, reclaim_job (ADR 0092),
  ReportJobOutcomeService and WorkerExecutionLoop (decision 7). A crash
  between the two writes leaves a finished or requeued job on a node that
  stays allocated, and this service does not see it, because it reads
  only leased-state jobs. ADR 0092 accepted this for reclaim_job, and this
  change extends it to the two outcome paths. A repair that recomputes a
  node's allocation from the jobs that hold it is tracked in
  #506.
- That the recovery writes of the two older services are atomic, or that
  they record their event in the same step as the job save. One
  transaction per recovery is tracked in #509.
- That a process was killed mid-recovery. The tests lose a write, and on
  Postgres they use a second connection for the competing lease.

## Alternatives Considered

- **Make the recovery one transaction.** The right long-term shape. The
  services work through repository interfaces that each take their own
  connection, so it needs a unit of work across four repositories and every
  recovery path. It would also leave alone the jobs already stranded in
  existing databases, which this repairs. It is tracked in #509.
- **Reclaim at the first sighting.** Rejected. It can requeue a job in the
  window between the release of its lease and the save of its outcome, and
  a second run of a job that completed is the incident this system exists
  to prevent.
- **Count passes instead of time.** Rejected. Two sightings in a row prove
  nothing about the time between them after an error ends a pass or a
  process stops leading, and the windows are bounded by pool waits, not by
  ticks. This was the first version of this change.
- **A first-seen timestamp stored with the job.** Rejected. A job has no
  timestamp for its last state change, and adding one is a schema change
  for a heuristic. The service holds the first-seen time itself, so only
  its own sightings are trusted.
- **Delete the lease last.** Rejected. It reopens the race ADR 0034 and ADR
  0052 closed, where a renewal lands after the decision to reclaim.
- **Derive a node's available capacity from its jobs.** Not chosen here, see
  decision 7.

## How to Verify

    NEUROMESH_STORAGE_BACKEND=memory pytest -q tests/application/reconciliation tests/infrastructure/repositories/test_job_repository_save_if_leaseless.py

The Postgres tests need a database whose name ends in _test (CONTRIBUTING):

    pytest -q tests/application/reconciliation/test_recover_leaseless_job_against_postgres.py tests/infrastructure/repositories/test_postgres_job_repository_save_if_leaseless.py

The regression test fails without the new step. With the step removed
from ReconciliationLoop, test_a_failed_job_save_after_the_lease_delete_is_repaired_once
fails, because the job stays RUNNING.
test_without_the_new_step_the_job_stays_stranded keeps the behaviour
before this change in the suite.

Each guard was removed by hand, the full application and repository
suites were run on Postgres, and these tests failed:

- The minimum age (`now - since >= self._min_age` replaced by `True`):
  test_a_job_is_reclaimed_only_after_the_minimum_age, among 13.
- The fenced write in ReportJobOutcomeService replaced by save():
  test_an_outcome_report_that_stalls_past_the_reclaim_does_not_credit_the_node_twice
  and, on Postgres,
  test_an_outcome_report_that_stalls_past_the_reclaim_is_refused.
- The fenced write in WorkerExecutionLoop replaced by save():
  test_run_once_does_not_save_an_outcome_for_a_job_reclaimed_while_it_stalled.
- FINISHING_STATUSES without CANCELLING:
  test_an_outcome_report_still_wins_over_a_cancel_request_saved_during_it,
  in memory and on Postgres, and seven existing cancellation tests.
- The copy in reclaim_leaseless_job:
  test_reclaim_leaseless_job_refused_changes_nothing and two more.
- The copy in take_running_job: 31 existing outcome tests on the
  in-memory backend.

The earlier round removed the clearing of sightings, the lease check in
the fenced write, the row lock on Postgres and the order of the outcome
report, and the test that names each one failed.
