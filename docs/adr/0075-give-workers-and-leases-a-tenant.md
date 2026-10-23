# ADR 0075: Give Workers and Leases a Tenant

## Status

Proposed. It becomes Accepted when `workers` and `leases` carry a
required tenant, the database refuses a worker, a running job or a
lease that crosses tenants, both repositories read by that tenant, and
every existing two-tenant test passes unchanged.

Related: ADR 0064 (points 2, 4 and 7), ADR 0066, ADR 0071 (decision
7), ADR 0073 and ADR 0074.

This ADR records how points 2, 4 and 7 of ADR 0064 are applied to
workers and leases. Slices 1, 2 and 3 are merged. The
Progress section says exactly what is. AetherGrid is not multi-tenant, and no document may
describe it as multi-tenant until ADR 0064 is Accepted.

## Context

A worker reaches its tenant only through its node (ADR 0073, decision
1), and a lease has no tenant at all. `workers.node_id` and
`workers.running_job_id` are single-column keys, and so are
`leases.worker_id` and `leases.job_id`. The database cannot refuse a
worker whose running job is in another tenant, or a lease whose worker
and job are in different tenants. Application code prevents both. ADR
0073 scoped the nine worker routes in the service layer, proved each
with a two-tenant test, and said in its decision 5 that this is not a
database guarantee.

`api_keys`, `nodes`, `jobs` and `events` already have the guarantee: a
unique `(id, tenant_id)`, composite keys that include the tenant, and
`ON DELETE SET NULL (column)` where a link must be cleared without
nulling the tenant. The baseline uses that form for
`jobs_assigned_node_same_tenant` on the PostgreSQL 16 that compose
pins. No test exercises it. ADR 0064 asks for one before it is
accepted.

The code today:

- `PostgresWorkerRepository` loads a worker's node with its tenant
  (`_node_from_row` reads `tenant_id`), so a worker's tenant is known at
  read time. Its `save` writes six columns and no tenant.
- `PostgresLeaseRepository.renew` is an `UPDATE` by lease id alone. A
  `Lease` is built in one place, `Lease.create`, called by
  `AcquireLeaseService`.
- `ReleaseLeaseService` reads a job with `get_by_id_across_tenants`
  because a lease holds no tenant. `ReportJobOutcomeService`,
  `CompleteJobService` and `FailJobService` read a job and its node the
  same way, and so does `WorkerExecutionLoop`. All are interim entries
  in `test_across_tenants_callers.py`.
- The foreign keys on a migrated database carry the default names
  `workers_node_id_fkey`, `workers_running_job_id_fkey`,
  `leases_worker_id_fkey` and `leases_job_id_fkey`.

The existing keys leave no orphans. `workers.node_id` is NOT NULL and
references `nodes`, and `leases.worker_id` is NOT NULL and references
`workers`, so every worker has a node and every lease has a worker. A
backfill through them cannot fail for lack of an owner. It can fail if
existing data already crosses a tenant, and it must then fail and say
so.

The threat model of ADR 0073 applies unchanged. What this ADR adds is a
database check for an application mistake (ADR 0064 point 7).

## Decision

1. **A worker's tenant is its node's, derived in the domain and stored
   for the database.** `Worker.tenant_id` is a read-only property that
   returns the tenant of its node. The repository writes it to
   `workers.tenant_id`. There is no second copy that could differ from
   the node's, and no worker fixture needs a new argument. A lease
   carries a required `tenant_id`. `Lease.create` takes it, and
   `AcquireLeaseService` passes the worker's and refuses to create a
   lease when the job is in another tenant. The writer chooses nothing
   (ADR 0074, decision 2).

2. **Backfill through the owner, never through the default tenant.** A
   worker takes the tenant of its node, then a lease takes the tenant
   of its worker, in that order and in one transaction.

3. **Add before remove (ADR 0071, decision 7).** Migration 0004 adds
   nullable `tenant_id` columns, backfills them, adds a unique
   `(id, tenant_id)` on `workers` and adds the composite keys of
   decision 4. It keeps the single-column keys, because a composite key
   skips a row with a null column and an older image still writes such
   rows. Migration 0005 ships in a later release. It repeats the
   backfill, stops with an error that names the count if any row still
   has no tenant, sets both columns NOT NULL and drops the
   single-column keys that the composite keys replace, using
   `DROP CONSTRAINT IF EXISTS` because a migrated database may differ
   from a fresh one.

4. **The database refuses links across tenants.**
   - `workers (node_id, tenant_id)` references `nodes (id, tenant_id)`,
     ON DELETE CASCADE as today.
   - `workers (running_job_id, tenant_id)` references
     `jobs (id, tenant_id)`, ON DELETE SET NULL (running_job_id), in
     the form of `jobs_assigned_node_same_tenant`.
   - `leases (worker_id, tenant_id)` references
     `workers (id, tenant_id)`, ON DELETE CASCADE.
   - `leases (job_id, tenant_id)` references `jobs (id, tenant_id)`,
     ON DELETE CASCADE.

   Existing rows that cross a tenant make the migration fail. They are
   not ignored.

5. **Repository reads are scoped after the column is required, not
   before.** A worker that an older image writes between 0004 and 0005
   has no tenant. An event with no tenant is invisible and harmless
   (ADR 0074, decision 7). A worker with no tenant would be invisible
   to its own agent, which would get 404 on heartbeat and lease
   renewal. Until 0005 the service filter of ADR 0073 stays the only
   read filter. After it, the methods of `WorkerRepository` and
   `LeaseRepository` take a required `TenantId` or end in
   `_across_tenants` (ADR 0064 point 4), the system actors use the
   second form, and both repositories join the signature test in the
   same change.

6. **The allowlist shrinks.** See decision 10.

7. **Every slice has tests written first, and each must fail for the
   right reason.** The migration tests build the rows themselves,
   because the test database holds no workers or leases.

8. **Every save writes the tenant.** The Postgres repositories set
   `tenant_id` on insert and in the `DO UPDATE` list. A worker that an
   older image wrote without one is repaired by its next save, and a
   live worker saves on every heartbeat, so the window between 0004 and
   0005 closes by itself for the workers that are running. 0005 still
   refuses if any row is left.

9. **Lease operations are scoped in the query.** `renew` takes the
   tenant and updates where the id and the tenant both match. A
   renewal that matches no row raises `LeaseNotFoundError`, as a
   missing lease does, and never creates one. It is the one write
   that reaches a lease by id alone, so it is where a service mistake
   would do the most harm, and the query makes it impossible. The
   other methods that read or remove one lease take a required
   `TenantId`. `list` and `delete_if_expired` serve the system actors
   and take the `_across_tenants` suffix (ADR 0064 point 4).

10. **The allowlist ends with system actors only.** In
    `test_across_tenants_callers.py` the credential lookup, the
    scheduler loop, the two reconciliation services and
    `worker_execution_loop.py` stay, each with its reason: the loop
    runs in the API process and acts on jobs for the whole fleet.
    `release_lease_service.py`, `report_job_outcome_service.py`,
    `complete_job_service.py` and `fail_job_service.py` leave in slice
    3, because each acts on one job for one caller and can pass that
    caller's tenant. Slice 3 does not merge while an entry that is not
    a system actor remains without a written reason.

11. **No lock-time machinery.** `workers` holds at most one row per
    node and `leases` at most one per worker. Both are bounded by the
    size of the fleet and not by event volume, so 0005 sets NOT NULL
    in one transaction with the rest of the migration and does not
    split it into a check that is added unvalidated and validated
    later. If either table is ever large, this decision is revisited.

12. **Release order is the gate for 0005.** 0004 ships in release N.
    0005 ships no earlier than release N+1, and an environment gets it
    only after the image it runs is N or later. The refusal in 0005
    names the count of rows with no tenant, and the pull request
    carries the query that finds them. An image from before N that
    writes after 0005 fails with a NOT NULL violation, which is loud,
    and never writes a row with no tenant.

13. **Required tests.** Each composite key has a test in which the
    database refuses a row that crosses a tenant. A test deletes a job
    that a worker is running and asserts that `running_job_id` is null
    and `tenant_id` is unchanged, which is the behavior ADR 0064
    requires proof of before it is accepted, and which no test covers
    today. The migration tests build their own workers and leases, with
    an existing worker whose running job is in another tenant to show
    that 0004 fails and changes nothing.

14. **A refused assignment leaves nothing behind.**
    `AssignWorkerService` takes the lease first. The worker accepts
    the job after the lease is held, and `WorkerAssigned` is recorded
    after the worker is saved. A lease refused because the worker row
    is missing or has no stored tenant, or because the worker's tenant
    differs from the job's, is reported as `NoAvailableNodeError`, so
    the scheduler unschedules the job and releases the node. The
    mismatch is also logged at error level, because the scheduler
    never pairs a job with a node of another tenant (ADR 0064 point
    6), so a mismatch means a mistake upstream. Only these refusals
    are handled. A job that already has a lease is refused with a
    `ValueError`, which is left to propagate: a lease row exists for
    it, and `RecoverExpiredLeaseService` reclaims the job if that
    lease expires, which takes 30 seconds with the default duration.
    The error ends that tick's scheduling and worker passes, and
    `api.py` logs it and runs the next tick. Catching every
    `ValueError` was rejected, because it would hide unrelated
    mistakes.

## Properties

1. A worker's tenant equals its node's, and the database refuses a row
   where they differ.
2. A worker's running job is in the worker's tenant, and the database
   refuses a row where it is not.
3. A lease's tenant equals its worker's and its job's, and the database
   refuses a row where either differs.
4. The nine worker routes answer as before. Every existing two-tenant
   test passes without a change.
5. An image from before this change can still write workers and leases
   after 0004 has been applied and before 0005 is.
6. After slice 3, no repository method returns a worker or a lease of
   another tenant unless its name ends in `_across_tenants`.
7. A renewal cannot change another tenant's lease, even if the service
   that calls it is wrong, because the query matches the tenant.

Status today:

| Slice | What | When |
|---|---|---|
| 1 | Migration 0004, the property on `Worker`, the field on `Lease`, writers that fill the tenant | merged, #380 |
| 2 | Migration 0005: required tenant, single-column keys dropped | merged, #397 |
| 3 | Scoped repositories, the shorter allowlist, both repositories in the signature test | merged, #399. The allowlist conversions followed in #400, #401, #402 and #404 |

## Alternatives Considered

### Store a tenant on `Worker` as a second field

Rejected. The invariant is that it equals the node's, and two copies
can differ in memory. Every worker fixture would also need a tenant
argument. The property gives the database the value without a copy.

### Scope the repositories first, as events did

Rejected. An event with no tenant is invisible and harmless. A worker
with no tenant would be invisible to its own agent. The order is
reversed on purpose.

### Make the tenant required in 0004

Rejected. It breaks the older image, and ADR 0071 does not allow a
migration that does.

### Add the NOT NULL check unvalidated and validate it later

Rejected. Both tables are bounded by the size of the fleet, and the
runner puts a migration in one transaction, so the split would not
shorten the lock.

### A trigger that fills the tenant

Rejected for the reason ADR 0074 gives: it moves logic into the
database, which no earlier tenancy change did.

### Leave the tenant on the node only

Rejected. It is today's state: correct in the routes, proven by tests
and not checked by the database. Points 2 and 7 of ADR 0064 would stay
open.

### Row level security

A different kind of change, and it belongs in its own ADR.

## Consequences

### Positive

- The database refuses a worker, a running job or a lease that crosses
  a tenant.
- A renewal cannot touch another tenant's lease even if its caller is
  wrong.
- Reads become one indexed query by tenant, and the interim
  `_across_tenants` entries for leases and outcomes go away.
- The route behavior and every route test stay as they are.

### Negative

- The backfill is two updates in one transaction, and 0005 holds a
  lock while it sets NOT NULL. Both tables are bounded by the size of
  the fleet, so the time should be small, but nothing has been
  measured. The test database has no workers or leases, so it says
  nothing about real tables.
- Between 0004 and 0005 a worker written by an older image has no
  tenant, and the composite keys skip it. The service filter of ADR
  0073 is the protection for that window, and it is not a database
  guarantee.
- In the same window, a worker with no tenant cannot take a lease.
  The composite key from the lease to its worker does not match the
  worker's row, so the insert is refused and `AssignWorkerService`
  raises `NoAvailableNodeError`. The scheduler puts the job back and
  tries again on its next tick, and each try is refused again until
  the worker is saved once, which its next heartbeat does (decision
  8). For a worker run by a standalone agent that is every 5 seconds,
  with jitter (`scripts/run_agent.py`), and the cluster loop sleeps 1
  second between ticks, so a job can be refused about five times in a
  row. This ADR makes no claim about the window for a worker that no
  agent runs. `AssignWorkerService` stops at the first refusal and does
  not try another idle worker on the node. It records no event for a
  refused try: `LeaseAcquired` is recorded after the lease is saved
  and `WorkerAssigned` after the worker is saved. The scheduler
  still records `JobScheduled` and then `JobUnscheduled` for every
  refused try, as it did before when no idle worker was registered
  on the node, so a job refused on every tick adds two events to the
  feed per tick.
- `LeaseAcquired` is now recorded before `WorkerAssigned` for the same
  assignment. If saving the `WorkerAssigned` event fails after the
  lease and the worker are saved, the assignment stands and only the
  event is missing. Each repository commits on its own, so nothing
  rolls the assignment back. The error ends that tick's scheduling and
  worker passes, and `api.py` logs it and runs the next tick.
- `Lease.create` gains a required argument, and every test that builds
  a lease directly changes.
- The in-memory repositories carry the change but have no composite
  key, so properties 1 to 3 hold there only through the writers, as
  they do for events.
- `worker_execution_loop.py` stays on the allowlist. It is a system
  actor, which is a judgment from reading its calls and not from
  reading its callers.

## Open questions

None.

Answered after slice 1:

- The sqlite backend keeps workers and leases in the in-memory
  repositories, as it does API keys. Only jobs, nodes and events use
  sqlite repositories (`_build_repositories` in
  `app/presentation/dependencies.py`). The composite keys of this ADR
  therefore exist on Postgres only, and this ADR claims no database
  constraint outside Postgres (ADR 0064 point 7). Workers and leases
  on that backend live in process memory.

## Follow-ups

- The wording of the Status of ADR 0064, after slice 3, so that it says
  what is proven and what is not.
- A test that pins the checksums of applied migration files.
- A decision on `CompleteJobService` and `FailJobService`. Neither has
  a caller in `app`. They were converted because decision 10 says to
  convert them, and deleting them is a separate change.
- A job with an assigned node whose node is not found in the job's
  tenant is skipped without a log line in `ReportJobOutcomeService`
  and `WorkerExecutionLoop`. On Postgres that state cannot occur:
  deleting a node clears the job's link (`ON DELETE SET NULL`), and
  `jobs_assigned_node_same_tenant` refuses a node of another tenant.
  The in-memory and sqlite backends have no such keys. If the state
  ever occurred there, a node of another tenant would keep its
  allocation and nothing would say so. Decision 14 logs a tenant
  mismatch at error level for the same reason, so these two should
  too. This is a gap in diagnosis, and not a resource leak on
  Postgres.

## How to Verify

```bash
grep -c "tenant_id" app/domain/entities/lease.py
```

It printed 0 before slice 1 merged and prints 1 or more now.
Slices 2 and 3 are merged.

```bash
grep -c "_across_tenants" app/application/workers/worker_execution_loop.py
```

It printed 4 before the loop was converted and prints 1 now. The one
that is left is the read of the worker, which the loop cannot scope
because it knows only a worker id.

## Progress

2026-10-18. Nothing is merged. This ADR is a proposal. `workers` and
`leases` carry no tenant, in the schema or in the entities. A worker
reaches its tenant through its node, which ADR 0073 enforces in the
service layer and proves with a two-tenant test for each of the nine
routes. The database does not check it.

2026-10-19. Slice 1 is written on the branch
`feat/workers-and-leases-tenant-slice-1` and is not merged. It has
migration 0004, the tenant property on `Worker`, the tenant on
`Lease` and writers that fill both. Review of the slice found three
flaws in `AssignWorkerService`. Each was fixed with a test written
first, and the full suite passes (903).

First, `WorkerAssigned` was recorded before the lease was tried. A
refused lease left the event behind, and the scheduler retries the
job on its next tick, so a worker with no stored tenant, which is
possible between 0004 and 0005, left one event per tick in
`GET /events` and `GET /jobs/{job_id}/history`. Against Postgres with
the event service wired in, three refused attempts left three events.
The event is now recorded after the worker is saved. The docstring of
`test_assign_worker_service_against_postgres_tenant.py`, committed
with the lease tenant, says a refused attempt persists nothing. That
was true of the worker and lease rows and false for events when it
was committed. It is true now.

Second, a lease refused for a tenant mismatch raised
`LeaseTenantMismatchError`, which neither `AssignWorkerService` nor
the scheduler caught. The job stayed SCHEDULED with its node
allocated. The scheduler's QUEUED query, `RecoverExpiredLeaseService`,
`RecoverOfflineNodeService` and `MarkDeadWorkersService` do not reach
such a job, because it has no lease and no stored worker holds it.
The refusal is now reported as `NoAvailableNodeError` and logged.

Third, `worker.accept` ran before the lease. The in-memory repository
returns the stored object, so a refused lease left the worker BUSY
with a job it held no lease for. The new test failed on that check
before the fix. `accept` now runs after the lease. The Postgres test
for a worker with no tenant already checked that the stored worker
stays idle.

The scheduler still records `JobScheduled` and `JobUnscheduled` for
each refused try, as it did before this slice for a node with no idle
worker registered.

2026-10-19. Slice 1 is merged as #380, squashed into one commit on main.
`workers` and `leases` now carry a nullable `tenant_id`, and the
database refuses a worker, a running job or a lease that crosses a
tenant, through the four composite keys that migration 0004 adds. The
single-column keys stay until 0005. `Worker.tenant_id` is a property
over its node, and `Lease` carries a required tenant. The three flaws
recorded above went in with it, each with a test that failed first.

The first test of `ON DELETE SET NULL (running_job_id)`, which ADR
0064 asks for, exists and runs against Postgres 16. Deleting a running
job clears the link and keeps the tenant. The test drops the
single-column key in a scratch schema first, so it proves the
composite key alone. The single-column key has the same rule in the
baseline, so deleting a running job clears the link with both keys in
place.

The full suite passes (903). Nothing reads by tenant yet. Slices 2 and
3 are not merged, and the status stays Proposed.

2026-10-19. The open question about the sqlite backend is answered. It keeps
workers and leases in the in-memory repositories, so the composite keys of
this ADR exist on Postgres only. Nothing in this ADR claims otherwise, and
the Open questions section now holds none.

2026-10-21. Slice 2 is written on the branch `feat/adr-0075-slice-2`
and is not merged. Migration 0005 gives a worker the tenant of its
node and a lease the tenant of its worker, stops and names the count
if any row is still without a tenant, sets NOT NULL on both columns and
drops the four single-column keys. All of it runs in one transaction.
The composite keys keep the delete rules of the keys they replace, and
the unique keys on `leases.worker_id` and `leases.job_id` stay.

The lease repository no longer derives a tenant from the worker or the
node, because a lease now always carries its own. Five tests built a
worker or a lease with no tenant through the application schema. After
0005 the database refuses such a row, so four were removed, and the
migration tests build those rows in a scratch schema at version 4. The
fifth, that a refused assignment records no event, was rewritten. It
now refuses because the assigned node has no idle worker. The full
suite passes (948).

Property 5 and decision 8 describe the window between 0004 and 0005.
They stop applying to an environment once it has 0005. Decision 12
still gates the release: 0005 does not ship in the release that
carries 0004. Slice 3 is not started, and the status stays Proposed.

2026-10-23. Slices 2 and 3 are merged. Slice 2 is #397 and slice 3 is
#399. Workers and leases carry a required tenant, the database refuses a
worker, a running job or a lease that crosses tenants, and the worker
and lease repositories read by tenant.

Four services and the worker execution loop still read across tenants
after slice 3. Decision 10 says each one leaves the allowlist or stays
with a written reason, so they were converted one at a time. Each
conversion is its own pull request, and each has a test that fails
against the old read.

- #400: `ReleaseLeaseService` reads the job in the lease's tenant. A
  lease in one tenant that names a job in another now fails closed. It
  raises `JobNotFoundError`, leaves the lease in place and records no
  event. A Postgres test runs the same release with events against the
  real repositories.
- #401: `CompleteJobService` and `FailJobService` take a tenant and read
  the job and the node in it. Neither has a caller in `app`, and
  `job_execution_support.py` calls them dead but tested, so only their
  tests changed.
- #402: `ReportJobOutcomeService` reads the node in the caller's tenant.
  A node of another tenant than the job is not found, and its allocation
  is not released. The test for it fails against the old read.
- #404: `WorkerExecutionLoop` reads the job and the node in the worker's
  tenant once the worker is loaded. The worker read stays across
  tenants, because the loop is handed a worker id and nothing else. Two
  guard tests record every across-tenants read on the job and node
  repositories during a full iteration in a non-default tenant, one for
  a plain completion and one for a cancellation requested mid-run. Both
  fail against the previous loop.

The allowlist in `test_across_tenants_callers.py` now holds system
actors only, and each entry has a reason. That test matches by file, so
it cannot tell the loop's one worker read from a new unscoped read. The
guard tests cover the loop. The full suite passed at 970 on the branch
before the loop change merged.

What this entry does not show. The composite keys exist on Postgres
only, as the 2026-10-19 entry says. Decision 12 gates 0005 behind a
release that carries 0004, and this entry does not record that the gate
was observed. The status stays Proposed until that is recorded and the
criteria in the Status section are checked against the merged code.
