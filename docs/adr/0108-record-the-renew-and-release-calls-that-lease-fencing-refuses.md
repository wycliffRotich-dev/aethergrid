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
