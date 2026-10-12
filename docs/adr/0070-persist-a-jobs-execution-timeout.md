# ADR 0070: Persist a Job's Execution Timeout

## Status

Accepted. This ADR closes the follow-up in ADR 0068 and ADR 0069 that
no job repository persists `execution_timeout`. It does not add a way
to set one. No request field or service parameter exists, so every job
created through the API still gets the default.

## Context

`Job.execution_timeout` is a `timedelta` that defaults to one hour. It
is load-bearing. The worker execution loop passes it to the subprocess
as its timeout (ADR 0012), `Job.has_timed_out` compares against it, and
the worker API serves it from `worker.running_job` as
`execution_timeout_seconds`, a field name `scripts/run_agent.py` also
reads.

No repository stored it. The `jobs` table had no column for it in
either SQL backend, and the job row is rebuilt in three places, one in
each job repository and a separate copy in the Postgres worker
repository. None of them passed it to `Job`, so a job loaded from
storage always had the default, whatever it was saved with. The
in-memory repository was not affected, because it keeps the `Job`
object itself.

The gap had no visible effect, because nothing sets a non-default
timeout. `CreateJobRequest` has no timeout field and
`CreateJobService.execute` takes none, so every job created through the
API gets one hour. Once a way to set a timeout was added, the gap would
have become a silent reset on the first reload.

## Decision

1. **One nullable column, in float seconds.** `jobs` gains
   `execution_timeout_seconds`, `DOUBLE PRECISION` in Postgres and
   `REAL` in SQLite. Seconds as a float and not an integer, because a
   sub-second timeout is valid (a test uses 0.5 seconds) and an integer
   column would drop the fraction.

2. **NULL means the domain default.** `save` always writes the job's own
   value, so only a row that predates the column is NULL, and it loads
   with `DEFAULT_EXECUTION_TIMEOUT`, the timeout it was already running
   with. The one hour constant is not copied into SQL, so the default
   has one definition.

3. **The schema change is additive and repeatable.** `schema.sql` adds
   the column to the `CREATE TABLE` and again with `ADD COLUMN IF NOT
   EXISTS`, the pattern `cancellation_requested_at` already uses.
   Applying the file a second time to a database that has the column
   skips every statement and changes nothing.

4. **SQLite upgrades in place.** `SqliteJobRepository` adds
   `_upgrade_execution_timeout_column`, which checks `PRAGMA
   table_info` and runs `ALTER TABLE` only when the column is missing,
   as `_upgrade_tenant_column` does for the tenant. The column is
   nullable, so no backfill is needed.

5. **All three mappers read it.** The Postgres and SQLite job
   repositories and the Postgres worker repository each rebuild a `Job`
   from a row, and each now passes the timeout. The worker
   repository's copy matters because the worker API serves
   `worker.running_job` through it.

6. **The schema reaches a database before the code does.** The save
   statements name the new column, so the column has to exist before
   this code runs against a database. The change is additive, and code
   that is already running names its own columns, so it ignores the new
   one. The safe order is schema first, then code.

## What the change found

- No test read a running job back through the worker repository. A
  search of `tests/infrastructure` for `running_job` found nothing
  before this change. The worker repository maps a job with its own
  copy of the code, so a test that only exercises a job repository
  cannot show the timeout missing there. The application tests use the
  in-memory repository, which stores the object and cannot lose it.
- Seven tests were added: three on the Postgres job repository, two on
  the SQLite one, and two that save a job and a worker and read the
  running job back through the Postgres worker repository.
- Before the code change, three tests failed: the Postgres round trip
  test, the SQLite round trip test and the SQLite upgrade test. The
  Postgres default and NULL tests passed, because the old code also
  satisfied them. They guard behavior that has to stay, not behavior
  that was broken, and each was later seen failing under its own
  change, listed next.
- Each of these changes fails the test written for it, and the file was
  restored and compared with a backup after every run:
  - dropping the timeout from the worker repository's mapper fails the
    running job test;
  - dropping it from the Postgres job mapper fails the Postgres round
    trip test;
  - removing the NULL fallback from the Postgres job mapper fails the
    NULL test;
  - removing the `ALTER TABLE` from the SQLite upgrade fails the
    upgrade test;
  - writing None for the timeout in the Postgres save fails the
    Postgres round trip test and the running job test;
  - writing a constant 1.0 in the Postgres save fails the Postgres
    round trip test and the default round trip test.
- The SQLite save and read paths were seen failing before the change.
  They were not mutated one by one afterwards.
- Full suite: 737 passed, up from 730. ruff is clean.

## Consequences

- A job's execution timeout now survives a save and a load on the
  Postgres and SQLite repositories and through the worker repository.
  The in-memory repository keeps it because it stores the object.
- Nothing sets a non-default timeout yet. The create job request has no
  such field and `CreateJobService.execute` takes no timeout, so every
  job created through the API still gets one hour, and a job that needs
  longer cannot be given more. Adding the field is a separate decision
  about its name, units and bounds, and this ADR does not make it. It
  has to come after this change, or a requested timeout would be reset
  to the default on the first reload.
- Rows that predate the column are NULL and load with the default, the
  timeout they were already running with. No backfill runs.
- The job row is still mapped in three places. A new `Job` column has
  to be added to all three, and the worker repository's copy is the one
  that was easy to miss. Collapsing them into one mapper is not done
  here.
- The column reaches an existing Postgres database only when
  `schema.sql` is applied to it, and ADR 0069 records that nothing does
  this at deployment today. Apply it before deploying this code.

## Alternatives Considered

**`NOT NULL DEFAULT 3600`.** Rejected. It copies the domain's default
into SQL, so changing `DEFAULT_EXECUTION_TIMEOUT` would leave the
database disagreeing with it. A nullable column where NULL means the
default keeps one definition.

**An integer number of seconds.** Rejected. A sub-second timeout is
valid, and an integer column drops the fraction.

**Persist it in the two job repositories and leave the worker
repository alone.** Rejected. The worker API serves
`worker.running_job`, which the worker repository builds with its own
mapper, so the timeout would survive a job round trip and still be lost
on that path.

**Add the request field first.** Rejected. A client could ask for two
hours and get one back after the first reload. Persistence has to land
before anything can set a non-default timeout.

## Follow-ups

- Decide how a client sets the timeout: the request field, its units,
  and its minimum and maximum. Nothing in this ADR chooses them.
- Replace the three copies of the job row mapping with one.
- The worker repository builds a node without its name, so a node
  loaded through a worker gets a random fallback name. Still open from
  ADR 0069.
- Apply `schema.sql` to an existing database as part of deployment.
  Still open from ADR 0068 and ADR 0069, and this change adds a column
  that depends on it.
