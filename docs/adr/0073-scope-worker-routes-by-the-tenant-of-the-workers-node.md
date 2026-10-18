# ADR 0073: Scope Worker Routes by the Tenant of the Worker's Node

## Status

Proposed. It becomes Accepted when every route under `/workers` is
scoped as Decision 7 lists, each with a passing two-tenant test, or is
recorded here as exempt with a reason.

Related: ADR 0064 (points 5 and 8), ADR 0066, ADR 0020 and ADRs 0034
to 0038.

This ADR records how ADR 0064 is applied to the worker routes. Part of
it merged before it was written: a test showed `GET /workers/{id}`
returning another tenant's job command, and that was fixed first. The
Progress section says exactly what is merged. AetherGrid is not
multi-tenant, and no document may describe it as multi-tenant until
ADR 0064 is Accepted.

## Context

ADR 0064 point 5 says a resource in another tenant is
indistinguishable from one that does not exist. Point 8 says the agent
endpoints first require that the key's tenant equals the worker's,
answering 404 otherwise, and only then apply lease fencing.

Workers carry no tenant of their own. The `Worker` entity has no tenant
field, and the baseline schema adds `tenant_id` to `api_keys`, `nodes`
and `jobs` only. A worker reaches a tenant through its node (ADR 0066).
Points 2 and 7 of ADR 0064 give workers a tenant and a composite
foreign key to their node. They are not done.

Before this ADR the worker routes took no caller. Two-tenant tests
showed that a key from one tenant could read another tenant's worker,
including the running job's `command`, which ADR 0020 reserves for the
assigned worker, could list every worker, and could reach the lease
renewal path of a worker it did not own.

Of the nine handlers in `app/presentation/routers/workers.py`, four now
take the caller: registration, list, get and lease renewal. `start`,
`complete`, `fail`, `cancel` and `heartbeat` do not. The outcome routes
go through `ReportJobOutcomeService`, which finds the worker by id,
checks that it holds the named job and checks the lease id. None of
those checks involves the caller's tenant. A lease id fences a stale
report. It does not authorize one.

## Threat Model

**Actor.** The holder of a valid API key in tenant T, calling the HTTP
API.

**Capability.** The actor can send any request. We assume the actor
knows or can guess worker ids, job ids and lease ids, because ids are
returned in responses and appear in logs. An unguessable id is not an
access control.

**Assets.** A worker's state, the command of the job it runs, its
lease, and the outcome recorded for its job.

**Goals the design must defeat.** Read another tenant's worker or its
job command. List another tenant's workers. Renew, start, complete,
fail or cancel on another tenant's worker. Learn from a response
whether another tenant's worker exists.

**Out of scope.** An unauthenticated caller, which `require_api_key`
handles. A compromised key inside its own tenant. A privileged operator
with database access.

**Not claimed.** Equal response time for a foreign and a missing
worker. A foreign worker costs one extra comparison. No test measures
it, and this ADR makes no claim about it.

## Decision

1. **A worker belongs to the tenant of its node.** This holds until
   workers carry their own tenant, and it stays true afterwards,
   because a worker's tenant must equal its node's.

2. **Every worker route takes the caller.** The handler passes
   `caller.tenant_id` to its service, and the service takes a required
   `TenantId` with no default. A caller that forgets it fails with a
   `TypeError` and not with a silent leak.

3. **A foreign worker is a missing worker.** The service returns `None`
   or raises the same `WorkerNotFoundError` it raises for an unknown
   id. The route answers the same 404, and no route answers 403 for a
   worker that exists.

4. **The tenant check runs first.** On the agent routes it runs before
   the check that the worker holds the job (409), before lease fencing
   and before any write. `ReportJobOutcomeService` releases the lease
   and saves the worker before it saves the job, so a check made after
   the first write would leave a foreign caller's effect behind a 404.

5. **The check is a filter in the service.** The repository still
   returns workers from every tenant and the service discards the
   foreign ones. This is not a database guarantee. Moving the filter
   into the repository, and adding a composite foreign key from
   `workers` to `nodes`, belong to points 2, 4 and 7 of ADR 0064 and to
   their own ADR.

6. **Every route has a two-tenant test, written first.** It is written
   before the change and must fail first, for the right reason: the
   foreign request succeeds where it should answer 404.

7. **Routes in scope.** The nine under `/workers`, listed in the
   Properties section below with their status.

8. **Heartbeat is scoped like the other routes.** The risk was that an
   agent holding a key from a different tenant than its node would be
   taken offline. The agent heartbeats its worker and its node in the
   same loop with one key, and `POST /nodes/{id}/heartbeat` already
   answers 404 for a node in another tenant. An agent with the wrong
   tenant's key was already failing its node heartbeat, so scoping
   worker heartbeat adds no new way for an agent to fail.

## Properties

Let K be a key in tenant T, W a worker whose node is in a tenant other
than T, and M an id that names no worker. For every route R in scope:

- **P1, indistinguishable.** R(K, W) and R(K, M) return the same status
  and the same body once the id is masked.
- **P2, no effect.** R(K, W) changes no stored worker, job, lease or
  node.
- **P3, owner unaffected.** A request from the worker's own tenant
  behaves as it did before this ADR.
- **P4, order.** The tenant check happens before the 409 check, lease
  fencing and every write.

Status today:

| Route | Scoped | Proven by |
|---|---|---|
| `POST /workers` | yes, via its node | registration test |
| `GET /workers` | yes | list test |
| `GET /workers/{id}` | yes | read and command tests |
| `POST /workers/{id}/lease/renew` | yes | renew test |
| `POST /workers/{id}/jobs/{job_id}/start` | yes | start test |
| `POST /workers/{id}/jobs/{job_id}/complete` | yes | outcome tests |
| `POST /workers/{id}/jobs/{job_id}/fail` | yes | outcome tests |
| `POST /workers/{id}/jobs/{job_id}/cancel` | yes | outcome tests |
| `POST /workers/{id}/heartbeat` | yes | heartbeat test |

## Alternatives Considered

### Give workers a tenant first, then scope the routes

Rejected for now. It needs a versioned migration, a backfill through
the owning node and a change to every place a worker is created, and
the routes stay open for as long as that takes. The rule in Decision 1
needs no schema change and remains correct afterwards.

### Answer 403 for another tenant's worker

Rejected. ADR 0064 point 5 requires that no response reveals that the
worker exists.

### Scope the reads now and leave the writes to the schema change

Rejected. A caller that knows a worker id, a job id and a lease id can
complete or fail another tenant's job. That is a write, and it is worse
than the disclosure the read tests found.

### Filter in the repository

Deferred, not rejected. It is where ADR 0064 point 4 ends up. Doing it
here would change the contract of `WorkerRepository` and both of its
implementations in the same change as the routes, and the join to
`nodes` exists only because workers have no tenant column.

## Consequences

### Positive

- A key from one tenant no longer reads another tenant's workers, their
  running job's command or their lease state.
- When the outcome routes are scoped, no key can complete, fail or
  cancel another tenant's job by knowing its ids.
- No migration is involved. The checksummed baseline and the startup
  check of ADR 0072 are untouched.
- Rollback is a revert of the commits. No stored data changes.

### Negative

- The repository still hands foreign workers to the service. `list`
  reads every worker and filters in Python, which is acceptable at
  current worker counts and wrong at scale. The schema work removes it.
- The lease renewal test checks P1 only. It does not assert that the
  foreign call left the lease unchanged, and it has no owner case. P2
  holds because the check runs before the service call. A state
  assertion is a follow-up.
- `ReportJobOutcomeService._finish` loads the job's node with
  `get_by_id_across_tenants`. After the ownership check this is a
  system lookup and not a leak, and it should become a scoped read once
  workers carry a tenant.
- `GET /events` was open across tenants when this ADR was written. It
  was never part of this ADR. ADR 0074 scoped it.
- The services change signature. The two read services had no caller
  outside the routers. The callers of the outcome service have not been
  read yet.

## Open questions

- Whether the cluster tick or the worker execution loop call
  `ReportJobOutcomeService`. If they do, a required tenant breaks them,
  and ADR 0064 point 4 allows a method named `_across_tenants` for a
  system actor.
- Whether the dashboard's `useWorkerHeartbeatKeeper` heartbeats with a
  key from the same tenant as the workers it lists. It lists them
  through `GET /workers`, which is scoped, so it should. The hook has
  not been read for this ADR.

## Follow-ups

- An ADR for giving workers and leases a tenant (ADR 0064 points 2 and
  7): a versioned migration under ADR 0071, a backfill through the
  owning node and worker and not through the default tenant, and
  composite foreign keys.
- The route registry test of ADR 0064 point 10, written after the
  routes are scoped so that it classifies what is true.

## How to Verify

```bash
pytest tests/presentation/test_worker_read_routes_tenant_isolation_api.py -q
pytest tests/presentation/test_worker_routes_tenant_isolation_api.py -q
pytest tests/presentation/test_worker_outcome_routes_tenant_isolation_api.py -q
pytest tests/presentation/test_worker_start_route_tenant_isolation_api.py -q
pytest tests/presentation/test_worker_heartbeat_route_tenant_isolation_api.py -q
grep -c "caller: Annotated\[ApiKey" app/presentation/routers/workers.py
```

The pytest commands pass. The last command prints the number of
handlers that take the caller. It prints 9, one for each handler.

## Progress

2026-10-16. `GET /workers/{id}`, `GET /workers` and
`POST /workers/{id}/lease/renew` are scoped. `GetWorkerService` and
`ListWorkersService` take a required `TenantId` and filter on the
tenant of the worker's node, and `renew_lease` takes the caller. Four
two-tenant tests cover them: another tenant's worker answers like a
missing one, another tenant's job command never appears in a response,
`GET /workers` lists only the caller's tenant, and another tenant's
worker cannot renew a lease. Each failed before the change and passed
after. The full suite passed (837).

2026-10-16. `complete`, `fail` and `cancel` are scoped. Before the
change, a test showed that a key from another tenant, given a worker
id, a job id and a lease id, got 200 from any of them. On complete,
the job ended COMPLETED, the worker went IDLE with no job and the
lease was deleted.
The three ids are returned in responses and written to logs, so they
are not a secret. `ReportJobOutcomeService.complete`, `fail` and
`cancel` now take a required `TenantId`, and a worker whose node is in
another tenant raises `WorkerNotFoundError` before the job check, the
lease check and every write. Three two-tenant tests cover them, one
per route: the foreign key gets 404, the body matches the one for a
missing worker once the worker id is masked, and the job, the worker
and the lease are unchanged. Each failed before the change and passed
after. Twelve existing service tests called the service without a
tenant and now pass `DEFAULT_TENANT_ID`. The full suite passed (840).

2026-10-16. `start` is scoped. Before the change, a test showed that a
key from another tenant, given a worker id and a job id, got 200 from
it. The worker and job ids are returned in responses and written to
logs, so they are not a secret. `StartJobService.execute` now takes a
required `TenantId`, and a worker whose node is in another tenant
raises `WorkerNotFoundError` before the job check and before the job
is started or anything is saved. The route takes the caller. One
two-tenant test covers it: the foreign key gets 404, the body matches
the one for a missing worker once the worker id is masked, and the
worker still holds its job, the job is still SCHEDULED and the lease
is unchanged. It failed with 200 before the change and passed after.
The five existing start route tests pass unchanged. No service test
called `StartJobService` directly. `start` went in its own commit, and
`complete`, `fail` and `cancel` went in one, because they share one
service helper. The full suite passed (841).

2026-10-18. `heartbeat` is scoped. Before the change, a test showed
that a key from another tenant, given only a worker id, got 200 from
it. The worker id is returned in responses and written to logs, so it
is not a secret. A heartbeat refreshes `last_seen_at` and returns an
OFFLINE worker that holds no job to IDLE, so a foreign key could keep
another tenant's worker out of the dead-worker sweep.
`Worker.belongs_to` now states the rule of Decision 1 in the domain.
`WorkerHeartbeatService.execute` takes a required `TenantId` and
raises `WorkerNotFoundError` for a worker in another tenant before it
heartbeats or saves anything. The route takes the caller and catches
`WorkerNotFoundError` only. It used to catch every `ValueError`, which
turned any `ValueError` raised inside the service into a 404.
`WorkerHeartbeatLoop`, which only tests construct, takes the tenant of
its worker with no default. Two route tests cover it. The foreign key
gets 404, the body matches the one for a missing worker once the
worker id is masked, and the worker's `last_seen_at` and OFFLINE
status are unchanged. The owner gets 200 and the worker returns to
IDLE. The foreign test failed with 200 before the change and passed
after. Service tests cover the foreign and the missing worker, and two
entity tests cover `belongs_to`. The full suite passed (867).
