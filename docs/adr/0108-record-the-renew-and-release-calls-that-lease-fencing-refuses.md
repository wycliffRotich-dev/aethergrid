# ADR 0108: Record the Renew and Release Calls That Lease Fencing Refuses

## Status

Proposed. This ADR decides what is kept when a renew or a release is
refused because the lease it names is no longer the lease of its worker.
Nothing in it is built yet and nothing is deployed. Each slice that is
built adds a dated entry under Progress. Related: ADR 0034, ADR 0036,
ADR 0038, ADR 0098, ADR 0106, ADR 0107.

## Context

ADR 0106, item 2, says the demo page shows a stale renew or release that
was refused, and that nothing records one today. RenewLeaseService and
ReleaseLeaseService compare the lease id the caller names with the lease
on record for its worker, and the release deletes by id (ADR 0034, ADR
0038). They raise NoActiveLeaseError when the worker holds no lease, and
LeaseNotFoundError when the lease on record is another one or the delete
removes nothing. The router answers both with 409. After that, no row, no
event and no log line keeps the lease id, the worker or the time of the
refusal.

An event cannot hold them. ADR 0107 explains why: an event is filed under a
job, and it has no column for a lease id. A payload was rejected there.

ADR 0107 keeps every lease that reclaim deleted, in lease_reclaims, with its
job id. A refused call that names such a lease can be tied to its job
through that table.

## Decision

1. Migration 0009 adds a table, lease_refusals, with one row for the first
   refusal of each kind of a lease that reclaim removed. Its columns are id,
   tenant_id, lease_id, worker_id, job_id, operation, reason and
   refused_at. Every column is required. operation is renew or release.
   reason is no_active_lease or lease_not_current. A check refuses any
   other value of either.
2. A composite key on tenant_id and lease_id points at lease_reclaims, so
   the database refuses a refusal for a lease that reclaim never removed.
   The refusal goes when its reclaim record goes. A composite key on
   job_id and tenant_id points at the job, as the keys of lease_reclaims
   do. The tuple tenant_id, lease_id, operation and reason is unique, so a
   second refusal of the same kind for the same lease changes nothing and
   the first one stays. worker_id has no key, because a node's workers are
   deleted with the node and the record must outlast them.
3. LeaseRefusalRepository, in app/domain/repositories, has two methods,
   save and list_for_lease. list_for_lease takes the tenant, and a record
   in another tenant answers like a missing one (ADR 0064, point 5). The
   PostgreSQL implementation and the in-memory one pass one shared
   contract. The sqlite and memory backends use the in-memory one.
4. RecordLeaseRefusalService reads the reclaim record of the lease id in
   the tenant. When there is none, it records nothing. When there is one,
   it saves a refusal that takes the job id from the reclaim record, the
   lease id and the tenant from the call, and refused_at from the time of
   the call. When the read or the save fails, the service logs one warning
   and does not raise, so a failed write cannot change the 409 that the
   caller gets.
5. RenewLeaseService and ReleaseLeaseService call the service once, just
   before each of their raises, with the operation, the reason, the worker
   id, the lease id and the tenant. An outcome report is refused through
   ReleaseLeaseService, so it is recorded with the operation release. Each
   service takes the recorder as an optional argument, so a service built
   without it behaves as before.
6. The body of the 409 is not stored here. The service never sees it, and
   the scenario driver of ADR 0106, item 1, records the real response it
   receives.
7. Nothing here is public. There is no view, no grant and no route, and
   ADR 0098 is not changed. The public read role has no privilege on the
   table, and a test says so. A view that shows these rows needs its own
   ADR, which amends ADR 0098, decision 1, on purpose.

## Consequences

- After a stale renew or release of a lease that reclaim removed, the lease
  id, worker, job, operation, reason and time of the refusal are in a
  table, one row for each kind.
- The table cannot grow from calls that name a lease id nobody held.
- The renew and release services stay free of SQL, because they call a
  service that takes repositories.
- A new table is a migration, a test and a review. The checksum of
  migration 0009 goes into the frozen list in the pull request that merges
  it.

## Alternatives Considered

- **An event with the lease id in its payload.** Rejected, for the reasons
  ADR 0107 gives for the reclaim record.
- **Record every refusal.** Rejected. Any caller of a tenant can send a lease
  id it made up, and each one would add a row. Keeping only the refusals of
  leases that reclaim removed bounds the table by the number of reclaims.
- **Store the body of the 409.** Rejected. The services raise exceptions and
  the router builds the body, so the services hold no body to store.
- **Record in the router.** Rejected. The router is the interface of the
  system and holds no tenant rule or lease rule. The services hold both.

Not claimed: safe to expose.

## Progress

2026-11-26. The storage for the record of a refused call.

Migration 0009 creates lease_refusals, with one row for each lease,
operation and reason in a tenant. The table has a key to the reclaim record
of the lease and a key to the job, and both name the tenant, so the database
refuses a refusal for a lease that reclaim never removed, a refusal in
another tenant than its reclaim record, and a refusal for a job of another
tenant. A row goes when its reclaim record or its job goes. worker_id has no
key, because the worker of a refused call may no longer exist. The public
read role has no privilege on the table (decision 7).

LeaseRefusal.record takes the tenant, the lease id and the job id from the
reclaim record, and takes the worker from the refused call. The port keeps
the first refusal of each kind and raises nothing on a repeat. The in-memory
and the PostgreSQL repository both pass the same contract.

New tests, 62: entity 10, in-memory contract 12, PostgreSQL contract 14,
migration 25, frozen migration list 1.

Flaws found and fixed. The tenant rule test of ADR 0064, point 4, failed
until the new entity and the new repository were added to its lists. The
first run of the deliberate breaks left four breaks standing: the lease term
dropped from the read in both repositories, and the lease id and the tenant
id dropped from the key of the in-memory repository. No test kept two leases
of one tenant, and the test of two tenants used refusals of different kinds.
Two tests were added to the shared contract, which run for both
repositories, and two to the migration test. The keys of the table gained
the same tests.

What each deliberate break turned red, in the real tests.

Migration 0009, 18 breaks. Every one of them also turned the frozen list
test red, because the file changed. Besides that test: the unique key
dropped (1 test), and the unique key without lease_id, without tenant_id,
without operation, without reason, and narrowed to tenant and lease (1 each).
The operation check dropped (1), the reason check dropped (1), the operation
check without release (3), the reason check without lease_not_current (3),
the operation check that also accepts cancel (1). The reclaim key dropped
(4), the job key dropped (2), the reclaim key without its cascade (1), the
job key without its cascade (1). The operation column made nullable (1), the
primary key dropped (1), SELECT granted to the public read role (1).

PostgreSQL repository, 22 breaks. The conflict target moved to the id (1).
DO NOTHING replaced by DO UPDATE (1). The tenant term ignored in the read
(3), the lease term ignored in the read (1). The order dropped (1), the
order reversed (1). On save: the operation always renew (4), the reason
always no_active_lease (3), the worker column given the job id (10), the id
given the lease id (11), the tenant given the job id (11), the lease given
the worker id (11), the job given the lease id (11), the time moved by a
year (10). On read: the operation always renew (4), the reason always
no_active_lease (2), the id given the lease id (10), the tenant given the
job id (10), the lease given the job id (10), the worker given the job id
(10), the job given the worker id (10), the time moved by a year (10).

In-memory repository, 8 breaks. setdefault replaced by assignment (1). The
tenant ignored in the read (3), the lease ignored in the read (1). The sort
reversed (1). The key without tenant (1), without lease (1), without
operation (1), without reason (1).

Entity, 9 breaks. The worker taken from the reclaim record (1), the time
taken from the reclaim record (1), the id taken from the reclaim record (1).
The tenant (1), the lease (1) and the job (1) not taken from the reclaim
record. The operation always renew (2), the reason always no_active_lease
(2). The entity not frozen (1).

Enum values, 4 breaks. Each of the four values changed (1 test each).

No break survived.

Not claimed: safe to expose.
