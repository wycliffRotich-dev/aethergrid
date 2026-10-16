# ADR 0072: Check the Schema Version When the Application Starts

## Status

Accepted on 2026-10-15. It was Proposed when it was written, with
nothing implemented. The check has merged, and the Progress section
below records what was found on the way. The original text of the ADR
is unchanged.

## Context

ADR 0071 Decision 6 says the application checks the schema at startup
and refuses to run against a database that is behind. The runner, the
baseline and the compose step have merged. The check has not, so
nothing in the application looks at the schema. The only protection is
the order in compose: `neuromesh` waits for the `migrate` service to
complete.

That order covers one way of starting the application. It does not
cover a database restored from an older backup, a deployment that does
not use this compose file, or a migration that someone forgot to run.
In each of those the application starts and then fails on writes, which
is the failure ADR 0071 was written to remove.

`lifespan` in `app/presentation/api.py` already waits for the pool
before it starts the cluster loop (ADR 0046). The pool is `None` under
`sqlite` and `memory`, and its connections use `autocommit=True` with
no `search_path` option, so an unqualified table name resolves the same
way for the application as for the runner.

The runner now has `plan_migrations`, a function that compares the
recorded history with the migration set and touches no database. It
reports the migrations still pending and the recorded versions that are
ahead of the image, and it refuses a hole, a recorded version below the
highest that has no file, and a changed checksum.

ADR 0046 records that the application respects the boundary between
the domain and the infrastructure everywhere except the health
endpoint, and calls that exception "deliberate, narrow, not a
precedent". The check reads a table, so this ADR has to say why it does
not need a repository.

## Decision

1. **The check is an infrastructure function.** It lives in
   `app/infrastructure/migrations`, takes a connection pool and the
   migration set, and imports nothing from FastAPI. The domain and the
   application layer do not change.

2. **It calls `plan_migrations`.** The checksum rule has one
   implementation. A non-empty `pending` means the database is behind.

3. **It runs once, after `pool.wait` and before the cluster loop
   starts.** A failure therefore stops the process before any
   scheduling happens. The function is blocking, so `lifespan` calls it
   on a worker thread, as it does for `pool.wait`.

4. **It only reads.** It never creates `schema_migrations`. It tests
   for the table with `to_regclass('schema_migrations')`, unqualified,
   so it resolves through the same search path the runner used. A
   missing table raises one message that says to run the migrations.

5. **A refusal stops startup.** A behind database, a missing table, a
   hole, a missing file below the highest version and a changed
   checksum each raise `MigrationError`, whose message names what is
   wrong. `lifespan` does not catch it. The existing test for a pool
   that never becomes ready shows that an exception raised in the
   lifespan propagates through `TestClient`. That the same failure
   makes uvicorn exit non-zero is not yet shown and is confirmed in
   the implementation pull request.

6. **A database that is ahead of the image is allowed.** The check logs
   one warning that names the versions and starts normally. This is
   Decision 6 of ADR 0071, and it is what the runner now does.

7. **Nothing runs under `sqlite` or `memory`.** The pool is `None`
   there, so `lifespan` skips the check (ADR 0071 Decision 8).

8. **`lifespan` reaches the check through `dependencies.py`.** That
   module is the composition root, and `api.py` takes everything else
   from it. `lifespan` calls the check by name, so the existing
   lifespan tests, which already replace `get_connection_pool`, can
   replace the check the same way.

## Alternatives Considered

### Report the problem on a readiness endpoint and keep running

Rejected. A process that is up but unready hides a broken deployment
behind something that looks alive, and nothing in `docker compose up`
would show it. Exiting fails where the deployment can see it.

### Add a repository method that returns the schema version

Rejected, for the reason in ADR 0046: `InMemory` and `Sqlite`
repositories would have to implement a method that means nothing to
them. The schema is a persistence detail, so the check stays in the
infrastructure layer and the domain does not learn it exists.

### Check on every request

Rejected. The schema cannot change while the process runs unless
someone migrates it underneath the application, and the cost of a query
would land on traffic.

### Let the check apply the missing migrations

Rejected. ADR 0071 Decision 5 keeps the rollout in control of when the
schema changes, and an application that can change its own schema would
need the right to do so while it serves requests.

## Consequences

### Positive

- An application that starts against a database that is behind now
  exits with a message that names what is missing, where before it
  started and failed on writes.
- The history rules have one implementation, and `plan_migrations` has
  tests that need no database.
- The protection no longer depends on the compose file.

### Negative

- Startup has a new failure mode. Tests that enter the lifespan on the
  postgres backend need a migrated database. CI and the README already
  run the runner first.
- The check cannot tell whether an ahead schema still works with the
  running code. Decision 7 of ADR 0071 (add before remove) is a
  convention, and nothing here enforces it.
- The existing lifespan tests pass a `MagicMock` as the pool, so they
  will replace the check, as they replace `get_connection_pool`.
- The check sits beside a documented exception to the layering in ADR
  0046, and it is a second place where the presentation layer is handed
  something from the infrastructure. It adds no new import from
  `api.py`.

## Open questions

- Whether the runner should wait for the database the way `lifespan`
  does. ADR 0046 records that the official Postgres image can report
  healthy before the real instance is up, with a gap of about five
  seconds on a fresh volume. The runner calls `psycopg.connect` once
  with no retry. One `migrate` run exited 1 and was never explained.
  Six cold starts on fresh volumes afterward all exited 0, so it is not
  reproduced. A retry would close a failure mode that is documented for
  the same image, but there is no evidence that it fires for `migrate`.
- Whether the log line for an ahead database should also appear in the
  `migrate` output. It currently prints "nothing to apply".

## Follow-ups

- The check and its tests, as one pull request: a migrated database
  passes, a behind database, a missing table and a changed checksum
  each stop startup, an ahead database starts and logs, a `None` pool
  skips the check, and a failing check stops startup before the cluster
  loop begins.
- Run the rollback through compose, which has been run only through the
  command line so far.

## Progress

2026-10-15. The check is implemented on its own branch. `check_schema`
in `app/infrastructure/migrations/startup_check.py` calls
`plan_migrations`. `lifespan` calls `check_database_schema(pool)` from
`dependencies.py` on a worker thread, after `pool.wait` and before the
cluster loop starts, with the pool it waited on. The function takes the
pool as an argument, which Decision 8 did not say. A first version
looked the pool up on its own, and the two lifespan tests that replace
`get_connection_pool` then ran the real check against the live test
database without saying so.

A flaw found by running the suite. The first version of the check read
rows by position. The full suite then failed in 26 tests that enter the
lifespan, all with `KeyError: 0`. Each of them passed alone, and the
same 26 failed with the new lifespan tests excluded, so the order of
tests was not the cause. The Postgres repositories set `row_factory` to
`dict_row` on the pooled connections they borrow (25 assignments in 7
repository files), and nothing resets it, so the next borrower of that
connection gets dict rows. A test that sets `dict_row` on a borrowed
connection and then runs the check reproduced the failure. This ADR did
not foresee it, and an earlier statement that these tests would pass
because the test database is migrated was wrong.

The check now asks for tuple rows on its own cursor and does not depend
on the row factory it finds. The cause is still in the repositories. New
code that reads from the pool by position meets the same trap, and it is
not fixed here.

A fix in the pool was tried and removed. `ConnectionPool` takes a
`reset` callback that restores the default row factory when a connection
is returned. With it set, 16 presentation tests failed with
`psycopg.OperationalError: connection socket closed`, and they failed the
same way when the callback did nothing, so the cause is the callback
being set at all. In the installed `psycopg_pool` (3.3.1), a pool with a
`reset` callback returns each connection through a task on a worker
thread, where a pool without one returns it in the calling thread. Some
code in the application depends on the inline return. Which code was not
found, and the callback was removed instead of worked around.

The leak is still in the repositories. The fix that does not change how
the pool returns connections is for each repository to ask for dict rows
on its own cursor and stop setting the factory on the connection. That
touches 25 sites in 7 files and is a separate change.

Run locally: the check tests (8), the presentation tests (107) and the
full suite (814) pass.

Not shown yet: that uvicorn exits non-zero when the lifespan raises, a
cold start through compose with the check in place, a database that is
behind stopping the container, and the rollback through compose.

2026-10-15, through compose. Every item in the paragraph above was run
against the real image on a throwaway project:

- A database whose history was emptied, with the tables kept, stopped
  the application. The container exited with code 3 and the log ended
  with "the database is behind this build: not applied:
  0001_baseline.sql". uvicorn exits non-zero when the lifespan raises.
- A cold start on a new volume came up healthy, with `migrate` exited 0
  and `neuromesh` running.
- A database with an extra recorded version 0002 started, and the log
  held one warning that the database is ahead of this build and names
  0002.
- The `migrate` service run against that same database printed "nothing
  to apply" and exited 0, so a rollback of the code is not blocked.

Two things came out of the runs:

- A first attempt ran old code. The image tag `neuromesh-app:local` is
  shared by the whole Docker daemon, and a partial `up` that names only
  `migrate` builds nothing for `neuromesh`, so the application started
  from an image that predated the check and started against an empty
  history. A run that names `neuromesh` with `--build` used the new
  code. The documented command in the README builds every service and is
  not affected.
- `docker compose up --wait` naming only `migrate` returned while the
  container still showed `running`. It showed `exited 0` five seconds
  later. For a service with no healthcheck, `--wait` is not a reliable
  signal that a one-shot has finished.

2026-10-16. The leak in the repositories is fixed. Each of the seven
Postgres repositories now asks for dict rows on its own cursor and does
not set `row_factory` on the connection it borrows. The 25 assignments
in 7 files counted on 2026-10-15 are gone: api key 3, event 2, job 5,
lease 3, node 5, tenant 3 and worker 4. The number of cursor sites is
not the same as the number of assignments. The tenant `save` used one
assignment for two statements, and each statement now has its own
cursor. The pool is unchanged, so connections are still returned in the
calling thread.

Each repository has a leak test in
`tests/infrastructure/repositories/test_postgres_repositories_leave_row_factory.py`.
It borrows from a pool of one, so the next borrower gets the connection
the repository just used, calls every public read, and checks that the
connection still has `tuple_row`. Each test failed before its repository
was changed and passed after. The tests for the worker, node and job
repositories save a row first so that every read runs to the end.

A second test keeps the leak from coming back.
`tests/infrastructure/test_infrastructure_never_mutates_pooled_connection_state.py`
parses every file under `app/infrastructure` and fails on an assignment
to `row_factory`, `autocommit`, `isolation_level`, `read_only` or
`deferrable`, including `setattr` with a literal name. The one file it
allows is `sqlite_connection.py`, by exact path: it configures a
connection it creates itself and no pool shares, so no other borrower
can inherit the setting. A test fails if that file moves. The test reads
source, so it does not see a setting made with a computed attribute name
or through SQL.

Reading the worker repository for this change showed a second problem.
`get_by_id` and `get_by_node_id` called `_to_entity(conn, row)` after
the `with` block had returned the connection to the pool, so its two
follow-up queries ran on a connection another caller could already hold.
Both calls are now inside the block. No test covers this. It would need
two threads and a pool of one, and it is not written.

Session state set through SQL was checked by search, not by test. `app/`
has no `SET`, `set_config`, temporary table, `LISTEN` or prepared
statement. The only advisory locks are in the migration runner, which
opens its own connection and does not borrow from the application's
pool.

The comment in `startup_check.py` said the repositories set the row
factory. It now says why the check asks for its own: the pool does not
reset connection state, so a borrowed connection can arrive with another
caller's setting. The `tuple_row` cursor stays.

Run locally: `ruff check app tests` is clean and the full suite passes
(826).
