# ADR 0092: Release a Node Only After the Job Is Saved

## Status

Accepted. The change and its tests are on branch
fix/reclaim-saves-job-before-releasing-node, and the full suite passes
(1324 tests).

Related: ADR 0011 and ADR 0029.

## Context

reclaim_job gives a job back to the queue after its lease expired or its
node went offline. Until this change it ran in the order lease, node,
job: the node's resources were released and the node saved first, then
Job.reclaim() ran, and the job was saved only if reclaim() succeeded.

Job.reclaim() raises InvalidJobTransition for a job that can no longer be
reclaimed, for example one that completed or failed in the meantime. The
node had already been credited by then. A job that finished had already
released its resources when its outcome was reported, so the second
credit made the node report capacity it does not have. When the node
hosts nothing else, Node.release stops at full capacity and hides the
extra credit. When it hosts another job, the node offers a core that is
already promised.

## Decision

1. reclaim_job calls Job.reclaim() before it touches the node. The job is
   saved if reclaim() succeeds, and the node is released and saved after
   that save. The node is passed in already resolved, so Job.reclaim()
   clearing assigned_node_id does not affect it.
2. When reclaim() raises InvalidJobTransition, reclaim_job returns False
   and does not credit the node, with one exception. A CANCELLED job is
   released once. CancelJobService cancels a queued or scheduled job with
   a status change and a save, and nothing else gives its capacity back.
   A COMPLETED or FAILED job released its capacity when its outcome was
   reported, so it is not credited again.
3. A job in CANCELLING that is finalized by Job.reclaim() is released by
   the success path, once.

## Consequences

- A job that can no longer be reclaimed no longer inflates a node's free
  capacity.
- A crash between the job save and the node save leaves capacity
  allocated. The node under-reports free capacity, which is the safe
  direction, where the old order could over-report it.
- Cancelling a scheduled job returns its capacity when reconciliation
  runs, as it did before this change.

## Not Claimed

- That the leak from a crash between the two saves is repaired. Nothing
  repairs it yet. A later change is planned to derive a node's available
  capacity from the jobs assigned to it, and this ADR does not claim it.
- That a job already finalized by Job.reclaim() and passed to reclaim_job
  a second time is credited only once. Reconciliation deletes the lease
  first and so does not revisit it, and no test covers a second call.
- That capacity updates are safe when two services change the same node
  at once. The scheduler, outcome reporting, the worker loop and
  reclaim_job each read a node, change its available figures and save the
  whole row, and two of them can overwrite each other.

## Alternatives Considered

- **Release the node when the job is cancelled.** Rejected for now. It
  gives CancelJobService a node repository and a lookup it does not have,
  and the existing test builds the service with a job repository only.
- **Keep the old order.** Rejected. It credits a node for a job that is
  not being reclaimed.
- **Do nothing for cancelled jobs and wait for a sweep.** Rejected. The
  leak happens on every cancelled scheduled job, so it is not a crash
  case that a sweep could be left to heal.

## How to Verify

```bash
pytest -q tests/application/reconciliation/test_cancelled_scheduled_job_keeps_node_capacity.py tests/application/test_job_execution_support.py
```

All of them pass.

## Progress

2026-11-10. The reorder made test_cancelled_scheduled_job_gets_its_node_capacity_back
fail. A cancelled scheduled job was no longer credited, because the
first version of the reorder returned before any release for every job
that could not be reclaimed. That was a flaw in this change, found by
the test and fixed in the same change by decision 2.

test_cancelled_scheduled_job_is_credited_exactly_once puts a second
allocation on the node, so a double credit would show as 7 cores and
15872 MiB instead of 6 and 15360. It passes.

The full suite passed with 1324 tests, none skipped, with
NEUROMESH_STORAGE_BACKEND set to postgres and the test database on
Postgres. The two reclaim test files build in-memory and SQLite
repositories directly, so the reclaim change has no test against
Postgres repositories.

Not claimed by this run: that a cancelled scheduled job's node credit
behaves the same through the Postgres node repository.
