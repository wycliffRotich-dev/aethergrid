# ADR 0067: Scope Node Reads by Tenant

## Status

Accepted. This ADR records how ADR 0064, points 4 and 5, were applied
to nodes. ADR 0064 stays Proposed, and nothing here changes that. Giving jobs a tenant followed in ADR 0068.

## Context

ADR 0066 gave every node a tenant and persisted it, but nothing read
it. Any valid key could still list, drain, heartbeat and delete every
node, and the cluster health, capacity and utilization routes
reported the whole fleet to every caller. ADR 0064 requires that a
node in another tenant answers exactly like a missing one.

## Decision

1. **The tenant is required on every route-facing read.**
   `NodeRepository.get_by_id`, `list` and `delete` take a required
   `TenantId`, and the tenant is applied inside the query in SQLite
   and Postgres and in the lookup in the in-memory repository. A
   node in another tenant cannot be fetched and filtered afterwards,
   because it is never fetched. `NodeRepository` and `Node` are
   registered in the repository tenant rule test, so an unscoped
   method fails the build.

2. **System actors use named across-tenants reads.** Three methods
   are added: `get_by_id_across_tenants`, `list_across_tenants` and
   `list_available_across_tenants`. The scheduler loop, recover
   offline node and recover expired lease act on the whole fleet by
   design. Complete job, fail job, report job outcome and the worker
   execution loop read a node from a job or worker that carries no
   tenant yet, so they use the same methods as an interim step.

3. **Who may call an across-tenants read is a visible list.** A test
   compares every file under `app/application` that calls an
   `_across_tenants` method with an explicit allowlist that gives a
   reason for each entry. A new caller fails the build until someone
   decides it belongs. A second test fails if any route calls one.
   The four interim entries are marked, and they leave the list when
   jobs and workers carry a tenant.

4. **`list_available` is removed.** Nothing under `app/` called it.
   The scheduler uses `list_available_across_tenants`. The draining
   rule is covered by tests on the new method, and the stale
   heartbeat test for SQLite moved to it with the same assertion.

5. **The tenant goes through `execute`, not the constructor.**
   `dependencies.py` builds each service once and shares it across
   requests, so a tenant stored on the instance would leak between
   callers. Get node, list nodes, list offline nodes, drain,
   heartbeat, remove offline node and the three cluster services take
   a required `TenantId` on `execute`.

6. **The routes pass the authenticated key's tenant.** The six node
   routes and the three cluster routes take the caller and pass its
   tenant. No request field names a tenant. Another tenant's node
   answers the same status and body as a missing id on get,
   heartbeat, drain and remove. Remove does not answer "still alive"
   for another tenant's node, since that would show that it exists.

7. **Registering a worker is scoped to the caller's tenant.** The
   `POST /workers` route looks the node up in the caller's tenant, so
   registering a worker for another tenant's node answers 404, exactly
   like a missing node. This is a behavior change: before it, any key
   could register a worker on any node.

## What the change found

- The first estimate of failing tests was low. Changing the service
  signatures broke 30 application tests, and two more were hidden
  behind earlier failures in the same test. Every one was a missing
  tenant argument, and none was a difference in behavior.
- After the routers changed, one production caller that had not been
  searched for, the register-worker route, still called a changed
  service. It was the only caller of the node service outside the
  node router. The suite caught it.
- Two checks confirmed that the new tests can fail. Removing the
  tenant filter from the in-memory `get_by_id` fails its contract
  test, and pinning the worker route's node lookup to the default
  tenant fails the test in which the owning tenant registers a
  worker.

## Consequences

- Node reads, lists and deletes, the node routes, the cluster routes
  and worker registration are tenant-scoped. This is covered by
  contract tests on every backend and by request tests with two
  tenants for each of those routes.
- Jobs, workers, leases and events still carry no tenant. The other
  worker routes are not scoped, the scheduler can still place a job
  on any node, and four services still read a node across tenants.
  AetherGrid is not multi-tenant, and no document may describe it as
  multi-tenant until ADR 0064 is Accepted.
- A node agent must use a key from its node's tenant. A key from
  another tenant answers 404 on that node's heartbeat.
- A deployment that predates tenancy keeps its behavior. Its keys and
  nodes were moved to the default tenant by the upgrades in ADR 0065
  and ADR 0066, so they still see one another.

## Alternatives Considered

**Change every caller in one step.** Rejected. Making the tenant
required on three methods breaks every caller at once. The work went
in three steps that each leave the suite runnable: add the named
reads, move the callers that have no tenant onto them, then make the
tenant required.

**Keep the old unscoped methods next to the scoped ones.** Rejected.
An unscoped `get_by_id` that anyone can still call is the silent
bypass ADR 0064 rejects. The across-tenants names and the caller
allowlist make the exceptions visible.

**Bind the tenant when the service is built.** Rejected, see point 5.

## Follow-ups

- Give jobs, workers, leases and events a tenant, with the scheduler's
  same-tenant rule and the composite foreign keys from ADR 0064, and
  remove the four interim entries from the allowlist.
- Scope the remaining worker routes.
- Pass the node's name through the worker repository. A node loaded
  through a worker gets a random fallback name.
- Make `list_available_across_tenants` mean the same in every backend.
  Postgres filters on draining only, while SQLite and the in-memory
  repository also require a live heartbeat.
- Apply `schema.sql` to an existing database as part of deployment.
  Today it reaches a database only through the compose init mount,
  which runs when the data volume is first created.
