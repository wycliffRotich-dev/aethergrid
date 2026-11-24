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

## Progress

2026-11-24. The storage for the record is built. The service that writes
it and the three recovery paths that call it are not part of this slice.

What is built: the entity LeaseReclaim, the enum LeaseRecoveryPath
(expired_lease, offline_node, worker_registered), the port
LeaseReclaimRepository, the in-memory and PostgreSQL repositories, and
migration 0008. LeaseReclaim.record takes a lease and the recovery path,
gives the record an id of its own and sets reclaimed_at from the time of
the call. The PostgreSQL repository saves with ON CONFLICT on the tenant
and the lease id and does nothing, so the first record of a lease stays.
The in-memory repository keeps the first record the same way. The
checksum of 0008 is in the frozen list.

How it is tested: 7 tests on the entity. One shared contract runs against
both repositories, 7 tests for the in-memory one and 9 for PostgreSQL,
which adds two refusal tests of its own. 22 tests on the migration, run
on a scratch schema built from the real migration files. They check the
columns, the primary key, the two foreign keys, each recovery path
accepted and an unknown one refused, a record for a missing job or for a
job in another tenant refused, the unique pair, the cascade, and that the
public read role holds none of the seven privileges on the table.

What each deliberate break turned red, in the real tests.

Repositories, 13 breaks. In-memory: the first record no longer stays (1
test), the key ignores the tenant (4), the read ignores the tenant (2).
PostgreSQL: a conflict raises (1), a conflict replaces the record (1),
the read drops the tenant (2), worker id and job id swapped on save (4),
lease times swapped (4), the recovery path not stored as given (2),
reclaimed_at read from the expiry (4), the record id read from the lease
id (4), the worker id read from the job id column (4), the lease id
written from the record id (4).

Migration 0008, 11 breaks. The recovery path check accepts anything (1
test). A fourth path is accepted (1, the same test). The unique pair is
dropped (1). Unique on the lease id alone (1). The job key does not name
the tenant (2). The cascade is dropped (1). The tenant key is dropped
(1). reclaimed_at may be null (1). worker_id is text (1). SELECT is
granted to the public read role (1). A key on worker_id (9).

The full suite found one flaw before this slice was committed. The
repository rule test of ADR 0064, point 4, did not list the new port, and
it failed with LeaseReclaimRepository neither scoped nor exempt.
LeaseReclaimRepository is now in its scoped list, and LeaseReclaim is among
the entities that carry their own tenant, which is how the rule accepts a
save that takes a record.

The repository rule test, 3 breaks. The port left out of the scoped list
(1 test). The record left out of the entities that carry a tenant (1). The
read without its tenant argument (1).

Two sentences of this ADR are corrected, because the code does something
other than they say. Decision 3 says both methods of the port take the
tenant. Only get_by_lease_id takes it. save takes a record, and the record
already carries its tenant. Decision 4 says the record takes its id from
the lease. The record has an id of its own, and the id of the lease is
kept in lease_id.

Not claimed: safe to expose.

2026-11-24. The three recovery paths keep the record.

RecordLeaseReclaimService builds the record of a deleted lease and saves it.
A failed save is logged as one warning with the lease id, the job id and the
error text, and is not raised, so a failed write does not stop a pass or undo
a reclaim (decision 4).

RecoverExpiredLeaseService records the lease with the path EXPIRED_LEASE,
once, after the job is reclaimed and before the job event is recorded. A
lease renewed before the delete, a job that cannot be reclaimed, a missing
job and a job of another tenant are not recorded.

RecoverOfflineNodeService records the lease it read and deleted with the path
OFFLINE_NODE, after a successful reclaim and before the event. A job with no
lease is reclaimed as before and nothing is recorded. A lease that is still
valid, or renewed before the delete, is not recorded.

CreateWorkerService reads the lease before it reclaims, because the reclaim
deletes it, and records it with the path WORKER_REGISTERED only when the lease
existed and the reclaim succeeded. A first registration and a worker with no
job record nothing.

Each service takes the recorder as an optional argument, and built without it
behaves as before. dependencies.py builds one recorder over the PostgreSQL
repository when the pool exists and over the in-memory repository otherwise,
and passes it to all three.

New tests, 47: recorder service 10, expired lease path 12, offline node path
11, worker registration 10, wiring 4.

What each deliberate break turned red, in the real tests.

Expired lease path, 9 breaks. The record call dropped (7 tests). The path
swapped to OFFLINE_NODE (2). The record placed before the reclaim (2), before
the check that the job was reclaimed (1), before the check that the delete
happened (5). An extra record in the branch of a missing job (2). The record
placed after the event (1). The recorder guard removed (1 new test, 8
existing). The recorder without its try and except (1 test here, 4 in the
recorder service tests).

Offline node path, 7 breaks. The record call dropped (6 tests). The path
swapped to EXPIRED_LEASE (1). The reclaim result dropped from the guard (1).
The lease check dropped from the guard (1). The record placed before the
reclaim (2), after the event (1). The recorder guard removed (1 new test, 1
existing).

Worker registration, 6 breaks. The record call dropped (5 tests). The path
swapped to EXPIRED_LEASE (1). The reclaim result dropped from the guard (1).
The lease check dropped from the guard (1). The lease read after the reclaim
(5). The recorder guard removed (1 new test, 1 existing).

Wiring, 7 breaks. The recorder dropped from each of the three builders (1
test each). A separate recorder built in each of the three (1 test each). The
repository always in memory (1).

No break survived.

Not claimed: safe to expose.
