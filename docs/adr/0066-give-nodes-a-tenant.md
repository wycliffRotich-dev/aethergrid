# ADR 0066: Give Nodes a Tenant

## Status

Accepted. This ADR records how ADR 0064, points 2 and 7, were applied
to nodes, as far as this change goes. It does not scope node reads
(see Consequences). ADR 0064 stays Proposed, and nothing here changes
that.

## Context

ADR 0065 scoped the key repository. Nodes come next in the order the
foreign keys of ADR 0064 force. Jobs reference `nodes(id)` through
`assigned_node_id` and workers through `node_id`, and a composite
foreign key can only point at a table that already carries the
tenant.

A node has no owner today. Any valid key can list, drain, heartbeat
and delete every node, and the scheduler can place a job on any node.
This change gives nodes a tenant and persists it. Scoping the reads is
a separate change, for the same reason keys were split in two: the
first change (#318) made every key carry a tenant, and the second
(#319, ADR 0065) scoped the repository.

## Decision

1. **A node carries a required tenant.** `Node.tenant_id` is required,
   has no default, and is declared before the defaulted fields. The
   tenant is fixed at registration by convention and by the repository
   rule, the same way it is for `ApiKey`. The dataclass is not frozen,
   so the type does not enforce it.

2. **The tenant comes from the caller's key.**
   `CreateNodeService.execute` takes a required `TenantId`, and
   `POST /nodes` passes the authenticated key's tenant. The request
   model has no tenant field. Pydantic ignores unknown fields by
   default, so a tenant in the body is dropped: it is neither honored
   nor rejected. A test sends another tenant's id in the body and
   asserts that the node still lands in the caller's tenant. Rejecting
   unknown fields would be stricter, but it changes every request
   model, so it is left out.

3. **The schema follows the key upgrade.** One transaction adds a
   nullable `tenant_id` that references `tenants(id)`, assigns every
   existing row to the default tenant, and sets the column NOT NULL.
   The column has no default, so an insert that forgets the tenant
   fails. A unique index on `(id, tenant_id)` is created for the
   composite foreign keys that arrive with jobs and workers. Those
   keys are not added here, because those tables have no tenant yet.

4. **A save never moves a node and never changes another tenant's
   node.** In Postgres and SQLite the upsert only updates a row whose
   tenant matches, and it never writes `tenant_id`. A blocked update
   affects no row, and the save raises `NodeTenantConflictError`. The
   in-memory repository raises when a stored node with the same id has
   a different tenant. The in-memory and Postgres repositories share
   one contract test for this, and SQLite has its own tests.

5. **SQLite upgrades in place.** The SQLite nodes table is created
   inline, so a file made before this change has no tenant column.
   SQLite only accepts NOT NULL on an added column that has a default,
   and a default would let a forgotten tenant land in the default
   tenant. So an upgraded file gets a nullable column and a backfill
   that runs on every start and is safe to repeat, while a fresh file
   is NOT NULL. The repository always writes the tenant, and ADR 0064,
   point 7, makes no database-constraint claim for SQLite. This is the
   first SQLite column upgrade in the codebase.

6. **The worker repository reads the node's tenant.** It already
   selects every node column, so the builder only needed to set the
   tenant.

## What the change found

- The Postgres node upsert matched on id only. Written the way the
  key upsert originally was, it would have repeated the gap ADR 0065
  closed, so the guard ships with the column.
- The in-memory repository stores the object it is given. A caller
  that changes `tenant_id` on an already stored node and saves it
  again is not detected there, because the stored object is the same
  one. Postgres and SQLite do detect it, since their rows keep the old
  tenant. The shared contract test saves a separate object with the
  same id, which behaves the same on all three.
- Two problems unrelated to tenancy were found and left alone. The
  worker repository builds a node without its name, so a node loaded
  through a worker gets a random fallback name. And `list_available`
  filters on draining only in Postgres, while the SQLite and in-memory
  versions also require a live heartbeat.

## Consequences

- Nodes carry a tenant, but nothing reads it yet. Node get, list,
  list available and delete, and the cluster health, capacity and
  utilization services, still look across tenants. `NodeRepository`
  is not under the rule test, and the scheduler can still place a job
  on any node. AetherGrid is not multi-tenant, and no document may
  describe it as multi-tenant until ADR 0064 is Accepted.
- A node created through the API belongs to the caller's tenant. A
  node created any other way must name a tenant, because the entity
  requires one.
- A save that conflicts on tenant now raises. Callers that save a node
  they loaded are unaffected, because that node carries its own
  tenant.
- An existing Postgres database upgrades when the schema file is
  applied, and an existing SQLite file upgrades when it is opened.
  Both are tested from a pre-tenant table.

## Alternatives Considered

**Scope the node reads in the same change.** Rejected. The reads feed
the scheduler, reconciliation, the job outcome services and the cluster
services, which need a tenant they do not have yet or an explicit
`_across_tenants` form. Together with the entity, the schema and three
backends, that is too large to review as one change.

**A default tenant on the column.** Rejected. An insert that forgot the
tenant would succeed and land in the default tenant, which is the
silent bypass ADR 0064 rejects.

**Reject unknown fields on the request model.** Deferred, see point 2.

## Follow-ups

- Scope the node repository: required `TenantId` on its methods,
  `_across_tenants` forms for the scheduler and reconciliation, the
  repository under the rule test, another tenant's node answering 404,
  and the node routes and cluster services filtered by tenant.
- Give jobs, workers, leases and events a tenant, with the scheduler's
  same-tenant rule and the composite foreign keys, as ADR 0064
  describes.
- Pass the node's name through the worker repository, and make
  `list_available` mean the same thing in every backend.
