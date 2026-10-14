# ADR 0072: Check the Schema Version When the Application Starts

## Status

Proposed. Nothing in this ADR is implemented. It records the design
before any code, so the pull request that follows can be reviewed
against it. It becomes Accepted when the check has merged.

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
