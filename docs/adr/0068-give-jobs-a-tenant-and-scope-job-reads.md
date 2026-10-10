# ADR 0068: Give Jobs a Tenant and Scope Job Reads

## Status

Accepted. This ADR records how ADR 0064, points 2, 4 and 5, were
applied to jobs. ADR 0064 stays Proposed, and nothing here changes
that.

## Context

After ADR 0066 and ADR 0067, nodes carried a tenant and every node
read was scoped by it. Jobs did not. Any valid key could still read,
cancel and retry any job, and read any job's event history, and a job
is a command that runs on someone's hardware.

The work followed the order used for nodes: first every job carries a
tenant, then the reads are scoped.

## Decision

1. **A job carries a required tenant.** `Job.tenant_id` is required,
   has no default, and is declared right after `resources`. No method
   on `Job` changes it, and a domain test pins that the tenant
   survives `unschedule`, `reclaim` and `retry`, the three paths that
   requeue a job. The dataclass is not frozen, so the type does not
   enforce it, as for `ApiKey` and `Node`.

2. **The tenant comes from the caller's key.** `CreateJobService`
   takes a required `TenantId` and `POST /jobs` passes the
   authenticated key's tenant. `CreateJobRequest` has no tenant field,
   and a test sends another tenant's id in the body and asserts that
   the job still lands in the caller's tenant.

3. **The schema follows the node upgrade.** One transaction adds a
   nullable `tenant_id` that references `tenants(id)`, assigns every
   existing job to the default tenant, and sets the column NOT NULL,
   with no column default. A unique index on `(id, tenant_id)` is
   created for the composite foreign keys that come later. The
   upgrade is tested from the frozen pre-tenancy schema: a job lands
   in the default tenant, a job without a tenant is refused on the
   upgrade path and on a fresh schema, and an unknown tenant is
   refused by the foreign key.

4. **A save never moves a job and never changes another tenant's
   job.** In Postgres and SQLite the upsert only updates a row whose
   tenant matches, never writes `tenant_id`, and raises
   `JobTenantConflictError` when the guard blocks the update. The
   in-memory repository raises when a stored job with the same id has
   a different tenant. In-memory and Postgres share one contract test
   for this, and SQLite has its own tests, including an upgrade of a
   table in the pre-tenant shape and opening the upgraded file again.
   SQLite keeps a nullable column on an upgraded file for the reason
   given in ADR 0066, point 5.

5. **Job reads take a required tenant.** `JobRepository.get_by_id`,
   `list_queued` and `list_recent` take a `TenantId`, applied inside
   the query in SQLite and Postgres and in the lookup in the
   in-memory repository. The unscoped `list` is removed. System
   actors read through `get_by_id_across_tenants` and
   `list_across_tenants`, and the caller allowlist test from ADR 0067
   was extended for the job callers. `JobRepository` and `Job` are
   registered in the repository tenant rule test, so an unscoped
   method on the interface fails the build.

6. **The services and routes pass the caller's tenant.** Get job,
   list jobs, list queued, cancel, retry and job history take a
   required `TenantId` on `execute`, and the six job routes pass the
   authenticated key's tenant. Cancel and retry look the job up in the
   caller's tenant before they change anything.

7. **Job history looks the job up first.** Events carry no tenant yet,
   so the history service looks the job up in the caller's tenant and
   returns the events only if it is found. Another tenant's job, a
   missing job and an id that is not a UUID all return the same empty
   history, so a caller cannot tell them apart. The route has no 404
   branch, so the empty result is the answer a missing job already
   got. Before this change, an id that was not a UUID went straight
   into the event query.

## What the change found

- The Postgres job upsert matched on id only. Written that way, it
  would have repeated the gap ADR 0065 closed for keys and ADR 0066
  closed for nodes, so the guard ships with the column.
- My first route test for retry failed in setup, not in the route: it
  assigned the failed job to a node id that does not exist, and
  `jobs.assigned_node_id` is a foreign key. The test now saves a real
  node in the job's tenant, which also stays correct when the
  composite foreign key arrives.
- Two checks showed that the route tests can fail. Pinning cancel's
  lookup to the default tenant fails the cancel case, and doing the
  same for retry fails the retry case; each time the other tests in
  the file still passed.

## Consequences

- Job creation, reads, lists, cancel, retry and history are
  tenant-scoped. Another tenant's job answers the same status and body
  as a missing id on get, cancel and retry, and the job is unchanged
  afterwards. This is covered by contract tests on every backend and
  by request tests with two tenants.
- The scheduler can still place a job on any node, and a job has no
  database link that requires its node to be in its tenant. Workers,
  leases and events carry no tenant, and the worker routes other than
  worker registration are not scoped. AetherGrid is not multi-tenant,
  and no document may describe it as multi-tenant until ADR 0064 is
  Accepted.
- A deployment that predates tenancy keeps its behavior. Its keys,
  nodes and jobs were moved to the default tenant by the upgrades in
  ADR 0065, ADR 0066 and this ADR, so they still see one another.
- A caller that used the removed `list` must use
  `list_across_tenants`, and the allowlist test decides who may.

## Alternatives Considered

**Return 404 for another tenant's job history.** Rejected. The route
returns an empty history for a missing job today, so an empty result
for another tenant's job is the same answer. A 404 for one case and an
empty 200 for the other would reveal that the job exists.

**Scope the reads in the same change as the column.** Rejected, as for
nodes. The entity, the schema and three backends are already a large
change to review, and the reads feed the scheduler, reconciliation and
the job outcome services.

**Keep the unscoped `list` next to the scoped methods.** Rejected, see
ADR 0067: an unscoped method that anyone can still call is the silent
bypass ADR 0064 rejects.

## Follow-ups

- The scheduler's same-tenant rule from ADR 0064, point 6, and the
  composite foreign key from `jobs.assigned_node_id` to
  `nodes(id, tenant_id)`. That key needs the column-list form of
  `ON DELETE SET NULL` so a node delete never tries to null
  `tenant_id`, which is available from PostgreSQL 15. The compose file
  pins 16.
- Give workers, leases and events a tenant, scope the remaining
  worker routes, and remove the interim entries from the allowlist.
- No job repository persists `execution_timeout`. Neither SQL backend
  has a column for it, so a job loaded from storage always gets the
  one hour default.
- Apply `schema.sql` to an existing database as part of deployment.
  Today it reaches a database only through the compose init mount,
  which runs when the data volume is first created.
