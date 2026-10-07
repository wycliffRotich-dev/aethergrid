# ADR 0064: Isolate Resources by Tenant, Enforced in the Domain and the Database

## Status

Proposed. This ADR becomes Accepted when the enforcement test
described under Decision, point 10, merges. Until then no document
may describe AetherGrid as multi-tenant.

## Context

`ApiKey` is the only authenticated identity (ADR 0022). Jobs,
nodes, workers, leases and events record no owner, so any valid key
can read and act on every resource in the system, and the cluster
health, capacity and utilization routes report the whole fleet to
every caller. ADRs 0055 to 0057 introduced ownership between keys
(`issued_by`), but that is a relationship among credentials, not a
boundary around data.

Serving more than one organization from one deployment needs a
boundary that holds even when an application mistake is made. A
tenant is that boundary: a set of keys and the resources they may
touch, with no path to any other tenant's resources.

ADR 0056 rejected backfilling an owner for keys that predate
`issued_by`, because nobody had ever recorded an issuer and
inventing one would falsify the audit trail. Tenancy differs in one
respect that matters: every row that exists today was created by one
deployment, so assigning it to one explicit default tenant records
a fact and invents nothing.

## Decision

1. **Tenant is a domain entity.** `Tenant` (id, name, created_at)
   and a `TenantId` value object live in the domain with no
   infrastructure imports, stored in a `tenants` table.

2. **Every tenant-owned record has a non-null tenant.** `api_keys`,
   `nodes`, `jobs`, `workers`, `leases` and `events` each carry
   `tenant_id UUID NOT NULL REFERENCES tenants(id)`. A schema
   upgrade creates one default tenant and assigns every existing
   row to it, inside one transaction, so a failed upgrade leaves
   the old schema intact. No unscoped state exists: nothing sits
   outside the boundary.

3. **The tenant comes from the credential, never from the
   request.** A key's tenant is fixed at issuance. A key issued
   over HTTP receives its issuer's tenant. No request body field,
   header or path parameter names a tenant. Creating a tenant and
   issuing a tenant's first key happen through scripts with direct
   repository access, the same bootstrap model as ADR 0015.

4. **The repository contract makes forgetting the tenant
   impossible to miss.** Every repository method that returns or
   changes tenant-owned records either takes a required `TenantId`
   or has a name ending in `_across_tenants`. The second form is
   reserved for system actors that act on the whole fleet by
   design: the scheduler loop, dead-worker marking, reconciliation
   and lease expiry. A test inspects the abstract repositories and
   fails on any method that is neither.

5. **Cross-tenant access is indistinguishable from absence.**
   Route-facing lookups filter by tenant inside the query. Another
   tenant's resource returns the same 404 as an id that does not
   exist, so no response reveals that it exists. Lists contain only
   the caller's tenant. The cluster health, capacity and
   utilization routes and the event feed compute over the caller's
   tenant only.

6. **Scheduling never crosses a tenant.** Nodes are tenant-owned
   and there is no shared pool. `Scheduler.select_node` considers
   only nodes whose tenant equals the job's, as a pure domain rule.
   A job's command therefore never runs on another tenant's
   hardware.

7. **The database refuses cross-tenant links.** `api_keys`,
   `nodes`, `jobs` and `workers` get a unique constraint on
   `(id, tenant_id)`. Composite foreign keys cover
   `api_keys.issued_by`, `jobs.assigned_node_id`,
   `workers.node_id`, `workers.running_job_id`, `leases.worker_id`
   and `leases.job_id`. A row that links two tenants cannot be
   written even if application code is wrong. The SQLite backends
   enforce the boundary through their repositories and the shared
   contract tests, and this ADR does not claim a database
   constraint there.

8. **Lease fencing is unchanged and sits behind the tenant check.**
   The agent endpoints (`start`, `complete`, `fail`, `cancel`,
   `lease/renew`, `heartbeat`) first require that the key's tenant
   equals the worker's, answering 404 otherwise. Lease identity
   fencing (ADRs 0034 to 0038) then applies as before.

9. **No cross-tenant capability exists over HTTP.** `keys:manage`
   and every other scope act within the caller's tenant only.

10. **The boundary is proven, not asserted.** One test enumerates
    every route in the application's OpenAPI schema and requires
    each to appear in a registry as either tenant-scoped or
    tenant-exempt with a written reason (the health probes and the
    root route). A route in neither fails the build, so a new route
    cannot ship unclassified. For every tenant-scoped route, a
    two-tenant test asserts that tenant B receives the response it
    would receive for a nonexistent id and that no state changed.
    A migration test starts from a pre-tenant database and asserts
    that every row lands in the default tenant.

## Consequences

- The boundary is enforced by application code and database
  constraints inside one shared database. It does not defend
  against a compromised application process or stolen database
  credentials, and nothing here should be described as if it did.
- Composite foreign keys with `ON DELETE SET NULL` must null only
  the link column, never `tenant_id`, which is not nullable. That
  needs the column list form of `SET NULL`, available from
  PostgreSQL 15. The compose file pins 16. A schema test must prove
  the behaviour before this ADR is accepted.
- Every existing test fixture needs a tenant. The change to the
  test suite is large and mechanical, and it ships in the same
  branch as the behaviour it supports.
- Rate limiting stays per key (ADR 0021). There are no per-tenant
  limits or quotas.
- Response shapes do not change, and tenant ids are not exposed in
  responses.
- For cross-tenant requests this ADR takes the 404 treatment in
  point 5. The 404 versus 403 ordering that ADR 0056 accepted for
  keys within one tenant is unchanged.
- New composite indexes on `(tenant_id, status)` for jobs and
  workers keep tenant-filtered lists from becoming sequential
  scans.

## Alternatives Considered

**A nullable `tenant_id`, with null meaning unscoped.** Rejected.
Every legacy key and row would sit outside the boundary, and the
unscoped state would be a permanent bypass that every future route
must remember to handle.

**PostgreSQL row-level security.** Deferred, not rejected. With a
connection pool it needs the tenant set per transaction, system
actors need a role that bypasses it, and it cannot carry over to
the SQLite backends. It remains a good defense in depth once the
repository contract in point 4 exists.

**A database or schema per tenant.** Rejected. The scheduler,
reconciliation and fleet views would have to fan out across
databases, and the single-store simplicity of ADR 0004 would be
lost.

**A shared node pool.** Deferred. It adds a fairness and isolation
story for workloads that share hardware, which deserves its own
ADR.

**Reading the tenant from a header or token claim.** Rejected. ADR
0015 chose opaque server-issued keys so that identity stays on the
server, and a caller-supplied tenant is spoofable by definition.

## Follow-ups

- A platform administration API and a `platform:admin` scope, once
  the trust model for it is decided.
- Per-tenant rate limits and quotas.
- Row-level security as defense in depth.
- Shared node pools with explicit sharing rules.
- Update the product deck's partly shipped slide only after this
  ADR is Accepted.
