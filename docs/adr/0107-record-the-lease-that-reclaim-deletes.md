# ADR 0107: Record the Lease That Reclaim Deletes

## Status

Proposed. This ADR decides what is kept when a recovery path deletes a
lease. Nothing in it is built yet and nothing is deployed. Each slice that
is built adds a dated entry under Progress. Related: ADR 0034, ADR 0036,
ADR 0038, ADR 0039, ADR 0075, ADR 0098, ADR 0106.

## Context

ADR 0106, item 3, says the demo page shows the lease that reclaim deletes,
and that the row is gone afterwards. Three paths delete a lease when they
reclaim a job:

- RecoverExpiredLeaseService deletes a lease that has expired.
- RecoverOfflineNodeService deletes the expired lease of a job whose node
  is offline.
- CreateWorkerService reclaims the job of a worker whose node registers
  again (ADR 0039), and the lease goes with it, deleted by job id.

After the delete, nothing keeps the id of the lease, the time it was
acquired or the time it expired. An event cannot hold them. An event is
filed under a job: it carries a job id that must equal its aggregate id,
and a composite key ties that job id to the tenant (migrations 0002 and
0003). It has no column for a lease id. Its payload is free text, the code
under app/ never sets one, and no public view shows it (ADR 0098,
decision 3).

A request to renew a lease, and each of the three outcome reports,
carries the lease id the caller believes it holds (ADR 0036, ADR 0038).
Once reclaim has run, nothing ties that id to a job.

## Decision

1. Migration 0008 adds a table, lease_reclaims, with one row for each
   lease that a recovery path deleted while it reclaimed a job. Its
   columns are id, tenant_id, lease_id, worker_id, job_id,
   lease_acquired_at, lease_expires_at, reclaimed_at and recovered_by.
   Every column is required. recovered_by is one of expired_lease,
   offline_node and worker_registered, and a check refuses any other
   value.
2. The tenant references tenants. A composite key on job_id and tenant_id
   points at the job, as the keys of events and leases do, so the
   database refuses a record whose job is missing or is in another
   tenant. The record goes when its job goes. The pair tenant_id and
   lease_id is unique, so a second record for the same lease changes
   nothing. worker_id has no key: deleting a node deletes its workers
   (ADR 0075), and the record must outlast them.
3. LeaseReclaimRepository, in app/domain/repositories, has two methods,
   save and get_by_lease_id. Both take the tenant, and a record in another
   tenant answers like a missing one (ADR 0064, point 5). The PostgreSQL
   implementation and the in-memory one pass one shared contract. The
   sqlite and memory backends use the in-memory one, as they do for
   leases.
4. RecordLeaseReclaimService builds the record from the lease and from the
   recovery path, and saves it. The record takes its id, tenant, worker,
   job and times from the lease, and reclaimed_at from the time of the
   call. When the save fails, the service logs the error and does not
   raise, so a failed write cannot stop a recovery pass or undo a
   reclaim.
5. Each path calls the service once, after reclaim_job has returned True
   and before the event is recorded, with the lease the path removed.
   RecoverExpiredLeaseService passes the lease of its loop.
   RecoverOfflineNodeService passes the lease it deleted itself.
   CreateWorkerService reads the lease before it reclaims, because it
   holds none today.
6. The service is an optional argument of each of the three, as the event
   recorder is, so a service built without it behaves as before.
7. Nothing here is public. There is no view, no grant and no route, and
   ADR 0098 is not changed. The public read role has no privilege on the
   table, and a test says so. A view that shows these rows needs its own
   ADR, which amends ADR 0098, decision 1, on purpose.

## Consequences

- After a reclaim, the id, worker, job, acquisition time and expiry of the
  deleted lease are in a table.
- The record of a refused renew or outcome report (ADR 0106, item 2) is
  decided in its own ADR. It reads this table, so that a refused lease id
  can be shown to have been a real lease that reclaim removed.
- The three paths stay free of SQL, because they call a service that takes
  a repository.
- A new table is a migration, a test and a review. The checksum of
  migration 0008 goes into the frozen list in the pull request that
  merges it.

## Alternatives Considered

- **A payload on the event.** Rejected. It has no named column, nothing
  checks its keys, and a view that showed it would amend ADR 0098,
  decision 3, for every event.
- **Keep the lease row and mark it reclaimed.** Rejected. A lease row
  blocks the next lease of its job and of its worker, because the table
  holds one lease per job and one per worker, so a kept row would stop the
  reassignment that reclaim exists to allow.
- **Record inside reclaim_job.** Rejected. The helper is shared by the
  three paths and does not read the lease. It deletes by job id unless its
  caller already deleted the lease, so only the callers hold it.
- **Write the record before the reclaim.** Rejected. reclaim_job returns
  False for a job that cannot be reclaimed, and a record of a reclaim that
  did not happen would be wrong.
- **A key from worker_id to workers.** Rejected. A node's workers are
  deleted with the node, and the record must outlast them.

Not claimed: safe to expose.
