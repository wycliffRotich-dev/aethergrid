# ADR 0074: Give Events a Tenant and Scope the Event Feed

## Status

Accepted. `GET /events` and `GET /jobs/{job_id}/history` read events
by the tenant stored on the event, each with a passing two-tenant
test, and the migration that makes that tenant required has merged.

Related: ADR 0064 (points 2, 4, 5, 7 and 10), ADR 0071 (decision 7),
ADR 0072 and ADR 0073.

This ADR records how ADR 0064 is applied to events. All three
slices are merged. The Progress section says exactly what is.
AetherGrid is not multi-tenant, and no document may describe it as
multi-tenant until ADR 0064 is Accepted.

## Context

ADR 0064 point 5 says a resource in another tenant must look like one
that does not exist. `GET /events` does not meet that today. The route
takes no caller, `ListEventsService.execute()` takes no tenant, and
`EventRepository.list()` returns every event. Any valid key, from any
tenant, lists the events of every tenant. The README describes the
route as a cluster wide feed, and the dashboard polls it.

An event holds an id, an aggregate id, an aggregate type, an event
type, a time and a payload. `RecordJobEventsService` never sets a
payload, so it is empty today. A foreign key therefore learns which
jobs exist, their ids, what happened to them and when. It does not
learn commands or resources. The job routes answer 404 to a job id from
another tenant, but this feed still hands those ids out.

Twelve call sites in nine files record an event with a job id as the
aggregate id. `RecordJobEventsService.record` defaults the aggregate
type to `Job`. In the `events` table `aggregate_id` is text and
`jobs.id` is a UUID, so no foreign key can link them as the tables
stand. Events carry no tenant column.

`GET /jobs/{job_id}/history` is scoped. `GetJobHistoryService` looks the
job up in the caller's tenant before it reads events, and says in its
docstring that events carry no tenant yet. That works for one job. It
cannot work for a list.

## Threat Model

The attacker holds a valid key in tenant B and knows nothing else.

- Can: list every event of tenant A, and learn which job ids exist,
  the event type of each step and when it happened.
- Cannot: read job commands or resources, or act on tenant A's jobs,
  because those routes answer 404 for a foreign id.
- Not defended: a compromised application process or stolen database
  credentials. ADR 0064 says the same.

## Decision

1. **Events are Job events.** Every writer passes a job id today, and
   the recording service defaults the aggregate type to `Job`. This
   ADR makes that a rule. An event for another kind of aggregate needs
   its own ADR, because this design ties an event to a job row.

2. **An event carries its tenant, and the writer does not choose it.**
   `Event` gets a required `tenant_id`. The recording service takes
   the job and reads `job.tenant_id` itself, so there is no tenant
   argument to get wrong. `record_for_job(job, event_type)` replaced
   the free form `record(aggregate_id, ...)`. `aggregate_type` stays
   on the event, so the response does not change. One writer holds a
   job id and no job: `ReleaseLeaseService` has a lease. It looks the
   job up with `get_by_id_across_tenants`, before it deletes the
   lease, and a missing job raises `JobNotFoundError` and changes
   nothing. That use is on the allowlist in
   `test_across_tenants_callers.py` and leaves it when leases carry a
   tenant. The service refuses a recorder without a job repository.

3. **The database refuses an event in the wrong tenant.** `events`
   gets a typed `job_id` and a `tenant_id`, a composite foreign key
   from `(job_id, tenant_id)` to `jobs (id, tenant_id)` in the same
   form as `jobs_assigned_node_same_tenant` (ADR 0064 point 7), and a
   check that `aggregate_id` equals `job_id` as text when `job_id` is
   set. A second check keeps `job_id` and `tenant_id` null together or
   set together, because a composite key skips a row with a null
   column and would let a row with a job and no tenant through. The
   text `aggregate_id` stays, so the API and the dashboard do not
   change.

4. **Reads require the tenant.** `list(tenant_id)` and
   `list_by_aggregate(aggregate_id, tenant_id)` take it with no
   default, as ADR 0064 point 4 asks. History becomes one query scoped
   by tenant, not a job lookup followed by a read. No across tenants
   method is added. One is added only when a system actor needs it.

5. **Add before remove.** ADR 0071 says a migration must work with the
   code that is running when it is applied, and after a rollback an
   older image runs against the newer schema. So `0002` only adds:
   nullable `job_id` and `tenant_id`, a backfill through the job, the
   key, the check and an index on `(tenant_id, occurred_at)`. A
   composite key does not check a row that has a null column, so an
   older image that writes events without a tenant keeps working.
   `0003` ships in a later release. It repeats the backfill for rows
   an older image wrote, sets both columns NOT NULL, and stops with an
   error if any event has no job.

6. **Backfill through the job, never through the default tenant.** An
   event takes the tenant of the job its `aggregate_id` names. The
   match is made as text, so a value that is not a UUID cannot abort a
   cast. An event with no matching job stays null, is shown to no
   tenant, and makes `0003` fail. Nothing guesses a tenant.

7. **A row with no tenant is shown to nobody.** The reads filter on the
   tenant column, and a null never equals a tenant. Between `0002` and
   `0003` an older image could write such rows, and they were
   invisible, not leaked. After `0003` Postgres refuses them. An
   upgraded SQLite file can still hold one, and shows it to nobody.

8. **Every route has a two-tenant test, written first.** For a list
   route, looking absent means tenant B receives none of tenant A's
   events, in the same shape as an empty feed. The test must fail
   first, for the right reason: B receives A's events.

## Properties

1. A tenant's feed holds only the events of its own jobs.
2. A request from another tenant receives none of this tenant's
   events, and the history of a job in another tenant is the same
   empty answer as the history of a job that does not exist.
3. The database refuses an event whose tenant differs from the tenant
   of its job.
4. An image from before this change can still write events after
   `0002` has been applied and before `0003` is.
5. An event with no tenant is shown to no tenant, and after `0003`
   Postgres refuses to store one.

Status today:

| Route | Scoped | How |
|---|---|---|
| `GET /jobs/{job_id}/history` | yes | events read by tenant |
| `GET /events` | yes | events read by tenant |

## Alternatives Considered

### Filter the feed through the jobs table in the service

It needs the tenant's job ids. The job repository has `get_by_id` for
one job, `list_queued`, `list_recent` with a limit, and two across
tenants methods that are for system actors only. One lookup per
distinct job on every poll is an N+1 on a feed that returns every
event. `list_recent` stops at its limit and would hide older events.
It is also a filter in the service with no database guarantee.

### Join the jobs table inside the event repository

One query and no schema change, but the event repository then knows
the jobs table, the in-memory repository cannot do it, and nothing in
the database checks the result.

### Let the caller pass the tenant to `record`

A caller could file an event under the wrong tenant with no error.
Reading it from the job leaves nothing to get wrong.

### Make the tenant required in 0002

It breaks the older image that writes events without a tenant, and
ADR 0071 does not allow a migration that does.

### Change `aggregate_id` to a UUID

It rewrites every event, and one value that is not a UUID would abort
the migration.

### A trigger that fills the tenant

Older images keep working, but the logic moves into the database,
which no earlier tenancy change did. A nullable column and a later
contract step reach the same result with plain constraints.

### Row level security

It is a different kind of change and belongs in its own ADR.

## Consequences

### Positive

- A tenant's feed holds only its own events, and the database refuses
  a mismatch.
- The feed is one indexed query, and so is the history route.
- The response shape does not change, so the dashboard code is
  untouched.

### Negative

- The leak stayed open until the read slice merged. Slice 2 closed it.
- The backfill is one update over every event, in one transaction. How
  long it takes depends on the size of the table, which has not been
  measured.
- `0003` backfills and sets NOT NULL in one transaction, so it holds a
  lock on `events` for the update and the scan. That time has not been
  measured either.
- Every writer needs the job. `release_lease_service` records with the
  lease's `job_id` and may need one more job lookup per release.
- SQLite and the in-memory repository carry the change too. SQLite
  upgrades itself in its constructor (ADR 0071 decision 8).
- `0002` is the first migration after the baseline. The test that says
  the real set is just the baseline changes in the same commit.
- The feed still has no limit. Scoping by tenant makes each feed
  smaller and does not cap it. Pagination needs its own ADR.

## Open questions

- Which environments still run an image from before slice 1, which
  decides when `0003` can be applied to each. This ADR does not
  record it.

Answered while writing slice 1:

- `ReleaseLeaseService` did not have the job and needed a lookup. See
  decision 2.
- In the application code, only `ListEventsService` calls
  `EventRepository.list`.
- SQLite and the in-memory repository keep property 3 only through
  the recorder, which reads the tenant from the job. Neither has a
  composite key, so nothing there refuses a wrong tenant. An upgraded
  SQLite file keeps its old events with no tenant, and they are shown
  to nobody.

## Follow-ups

- Slice 1: migration `0002`, the tenant on `Event`, recording from the
  job, and writes that fill both columns. The leak stayed open until
  slice 2.
- Slice 2: the scoped reads, the route takes the caller, and the
  two-tenant test is written first. This closes the leak.
- Slice 3: migration `0003`, which makes the job and the tenant
  required. Merged.
- An ADR for paging the feed.
- A later migration that drops `events_job_and_tenant_together`,
  which both columns being required makes redundant (ADR 0071,
  decision 7).
- The route registry test of ADR 0064 point 10. It lists every route.
  `GET /events` and `POST /workers/{id}/heartbeat` were unscoped when
  this was written and are scoped now (this ADR and ADR 0073). The
  three `/api-keys` routes still need a two-tenant check.

## How to Verify

```bash
pytest tests/presentation/test_event_routes_tenant_isolation_api.py -q
pytest tests/infrastructure/test_events_tenant_migration.py -q
pytest tests/infrastructure/repositories/test_postgres_event_repository_contract.py -q
grep -c "caller" app/presentation/routers/events.py
```

The pytest commands pass. The grep prints 1 or more, because the
route takes the caller. The tenant column is required, so Postgres
refuses an event with no tenant.

## Progress

2026-10-17. Nothing is merged. This ADR is a proposal. `GET /events`
still takes no caller and returns the events of every tenant to any
valid key. A foreign key learns job ids, event types and times. The
payload is empty today, so it does not learn commands or resources.

2026-10-17. Slice 1 is written. Migration 0002 adds `job_id` and
`tenant_id` to `events`, with the composite key and two checks. `Event`
carries a required `TenantId`, and all twelve writers record through
`record_for_job`, which reads it from the job. The Postgres and SQLite
repositories write it and skip an event with no tenant. The Postgres
save no longer overwrites a repeated id. Tests cover each of these,
including an event in another tenant's job being refused by the
database. The reads are not scoped yet: `GET /events` still lists the
events of every tenant that has one. The leak stays open until slice 2.

2026-10-18. Slice 2 is written. `EventRepository.list` and
`list_by_aggregate` require a `TenantId` in all three repositories,
and an event with no tenant never matches one. `GET /events` takes
the caller and `ListEventsService` passes its tenant, so a key sees
only the events of its own tenant. `GetJobHistoryService` reads by
tenant in one query and no longer looks the job up first. A job id
with no events in the caller's tenant gets the same empty answer
whether the job is missing, is in another tenant or has no events.
The new two-tenant test failed before the change, with one tenant
receiving another's events, and passes after it. Postgres refuses
an event with no job. The in-memory and SQLite repositories can hold
one, and the history of such a job is returned to its own tenant.
The leak in `GET /events` is closed. Slice 3, the migration that
makes the columns required, is not written.

2026-10-18. Slices 1 and 2 are merged, as #368 and #369. The full
suite passed (861) before slice 2 merged, and the migration and
Postgres repository contract tests pass against Postgres 16 (14
tests). `GET /events` has two route tests: the feed holds only the
caller's own events, and a tenant with no events gets an empty feed.
Slice 3 is not written. The tenant column is still nullable, an older
image can still write an event with no tenant, and such an event is
shown to nobody.

2026-10-18. Slice 3 is merged. Migration `0003` repeats the backfill
through the owning job, stops with an error that names the count if
any event still names no job, and sets `job_id` and `tenant_id` NOT
NULL, in one transaction with its version row. Three migration tests
were written first and failed before the file existed: a legacy event
takes the tenant of its job and both columns become required, Postgres
refuses an event with no job and no tenant, and an event that names no
job stops the migration and leaves the rows, the nullability and the
version table unchanged. The Postgres contract test that wrote a
tenantless row to prove it was shown to nobody could no longer set up
its state, so it now asserts that the database refuses the insert and
that the feed is unchanged. While the shared test database was still
at 0002, 26 presentation tests failed with the startup check's message
that the database is behind this build, and migrating it cleared them.
The full suite passed (872). All three slices are merged, both
routes have two-tenant tests, and the status is Accepted. Whether any
environment still runs an image from before slice 1 is not recorded
here, and `0003` must not be applied to one until no such image can
write events there.

2026-10-27. The follow-up that pins the checksums of the applied
migration files is done, and it is removed from the Follow-ups list.
`tests/infrastructure/test_applied_migrations_are_frozen.py` loads the
real files through `load_migrations` and compares each checksum with a
literal SHA-256, so editing or deleting a merged file fails in CI. It
also fails for a migration file that has no pin, so the next migration
cannot merge without one. Appending a newline to 0001 made it fail
with the file named in the message, and restoring the file made it
pass again. The pins were taken from the files as committed on main.
A change that edits a file and its pin together still passes, so a
reviewer has to refuse it. The full suite passed (1002).

2026-10-30. ADR 0064 was accepted today. Where this ADR says that ADR
0064 stays Proposed, or that AetherGrid is not multi-tenant, that was
true when it was written and is superseded. AetherGrid on main is now
multi-tenant as ADR 0064 defines it. The last entry of ADR 0064 records
what that covers and what it does not, including that no release carries
migration 0005 yet.
