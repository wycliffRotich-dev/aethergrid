# ADR 0069: Keep a Job on Its Own Tenant's Nodes

## Status

Accepted. This ADR records how ADR 0064, points 6 and 7, were applied
to scheduling. ADR 0064 stays Proposed, and nothing here changes that.

## Context

After ADR 0068, jobs and nodes both carried a tenant, but nothing
required them to match. The scheduler loop reads every queued job and
every available node across tenants, and the domain `Scheduler` chose
a node on liveness, draining, constraints and capacity alone. A job
could therefore run its command on another tenant's hardware, and the
database would not object, because the foreign key from
`jobs.assigned_node_id` to `nodes(id)` carried no tenant.

## Decision

1. **The tenant rule is a pure domain rule.** `Scheduler.select_node`
   keeps only nodes whose tenant equals the job's, and it checks that
   before anything about fit. The rule is a private `_same_tenant`
   method next to `_matches_constraints`, so the candidate filter reads
   as a list of named rules. The signature is unchanged. The scheduler
   loop is a system actor that still reads the whole fleet through the
   across-tenants methods, and the domain rule does the filtering, as
   ADR 0064, point 6, describes. Nodes are tenant-owned and there is no
   shared pool.

2. **The database refuses the link as well.** `schema.sql` adds
   `jobs_assigned_node_same_tenant`, a composite foreign key on
   `(assigned_node_id, tenant_id)` that references `nodes(id,
   tenant_id)`, using the unique index added with the node tenant
   column. A job that links two tenants cannot be written even if
   application code is wrong.

3. **A node delete clears only the link.** `ON DELETE SET NULL` names
   the column, so deleting a node nulls `assigned_node_id` and never
   tries to null the NOT NULL `tenant_id`. The column list form needs
   PostgreSQL 15, and the compose file pins 16.

4. **The old key is replaced without a gap.** The new key is added
   before `jobs_assigned_node_id_fkey` is dropped, in one block, so
   the column is never unprotected. A job with no node has a NULL
   `assigned_node_id` and is not checked.

5. **An inconsistent database fails the upgrade.** An existing job
   assigned to a node in another tenant makes the upgrade fail instead
   of being ignored. A database that predates tenancy has every row in
   the default tenant, so none can be inconsistent.

## What the change found

- The previous constraint accepted what the new one refuses. In a
  scratch schema, the old single column key accepted a job in one
  tenant that pointed at a node in another.
- No existing test assigned a job across tenants. The full suite
  passed after the composite key with no test changed.
- The rule is covered at two levels, and removing it fails both. With
  the `_same_tenant` condition removed from `select_node`, all three
  domain tests fail and all three scheduler loop tests fail. Each run
  restored the file, and the restored file was compared with the
  backup.

## Consequences

- A job is never placed on another tenant's node by the scheduler, and
  the database refuses a job that is assigned to one. Both are covered
  by tests: three domain tests, three tests through the scheduler loop
  with in-memory repositories, and four schema tests for the composite
  key, including an upgrade from the pre-tenancy schema.
- The two checks do different work. The loop charges a node's capacity
  in memory before it saves the job, so the foreign key alone would not
  stop a foreign node from being charged. The domain rule is what keeps
  a job from being matched to such a node at all, and the key is the
  backstop for a bug in the application.
- The loop tests cover placement only. They build the loop without a
  worker assignment service. Workers carry no tenant, and worker
  assignment is not covered by this ADR.
- The schema check was made against a scratch copy of the old
  definition, not by changing `schema.sql` itself, so it shows that
  the old design was open and not that the current file would be caught
  by a regression.
- AetherGrid is not multi-tenant. Workers, leases and events carry no
  tenant, and the worker routes other than worker registration are not
  scoped. No document may describe it as multi-tenant until ADR 0064 is
  Accepted.

## Alternatives Considered

**Filter nodes by tenant in the scheduler loop.** Rejected. The loop is
an application service, and a rule that decides where a command runs
belongs in the domain, where a pure test can reach it and where every
caller of `select_node` gets it.

**Rely on the foreign key alone.** Rejected, see Consequences. The
database would refuse the write after the node had already been
charged in memory.

**Keep the single column key and add a check in a trigger.** Rejected.
A composite foreign key states the rule declaratively and needs no
procedural code.

## Follow-ups

- Give workers, leases and events a tenant, with composite keys to the
  node and the job, scope the remaining worker routes, and remove the
  four interim entries from the across-tenants allowlist.
- `_fit_score` divides by a node's capacity for each dimension a job
  requests. Confirm that `can_host` makes a zero capacity unreachable
  there.
- No job repository persists `execution_timeout`. Neither SQL backend
  has a column for it, so a job loaded from storage always gets the
  one hour default. ADR 0070 adds
  the column and persists it.
- The worker repository builds a node without its name, so a node
  loaded through a worker gets a random fallback name.
- `list_available_across_tenants` means different things per backend.
  Postgres filters on draining only, while SQLite and the in-memory
  repository also require a live heartbeat.
- Apply `schema.sql` to an existing database as part of deployment.
  Today it reaches a database only through the compose init mount,
  which runs when the data volume is first created.

2026-10-30. ADR 0064 was accepted today. Where this ADR says that ADR
0064 stays Proposed, or that AetherGrid is not multi-tenant, that was
true when it was written and is superseded. AetherGrid on main is now
multi-tenant as ADR 0064 defines it. The last entry of ADR 0064 records
what that covers and what it does not, including that no release carries
migration 0005 yet.
