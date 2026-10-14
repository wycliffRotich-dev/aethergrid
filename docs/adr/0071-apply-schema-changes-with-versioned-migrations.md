# ADR 0071: Apply Schema Changes with Versioned Migrations

## Status

Proposed. Nothing in this ADR is implemented. It records the design
before any code, so the pull requests that follow can be reviewed
against it. It becomes Accepted when the runner, the baseline and the
startup check have merged.

## Context

`schema.sql` is the only description of the Postgres schema in the
application, and it reaches a database in one automatic way.
`docker-compose.yml` mounts it into `/docker-entrypoint-initdb.d`,
which the Postgres image runs only when the data volume is first
created. CI applies it with `psql -f` in two places, and the README
gives the same command for the test database. Nothing applies it to a
database that already exists. ADR 0068 and ADR 0069 both list this as
a follow-up.

The gap matters because the application and the schema change
together. ADR 0070 added a column that the save statements name, so
that code would fail on every job write against a database without
it. The compose file starts the `neuromesh` service as soon as
Postgres is healthy and checks nothing about the schema. Application
startup waits for the connection pool and then starts the cluster
loop, and it looks at no schema either. A search of `app/presentation`
found no schema or migration code.

SQLite is not affected. Its repositories upgrade the file themselves
when they are constructed (`_upgrade_tenant_column` and
`_upgrade_execution_timeout_column`).

The file is a workable baseline. It is one idempotent script of 289
lines, written to be applied again to any earlier database, with
guarded `ADD COLUMN IF NOT EXISTS` statements, two `DO` blocks and
three explicit `BEGIN` and `COMMIT` blocks. Applying it a second time
to the local test database during ADR 0070 skipped every existing
object and raised no error. Tests replay it from a frozen
pre-tenancy schema and apply it three times in a row, then check that
the default tenant is unchanged. Because the file controls its own
transactions, a runner cannot wrap it in one.

The file is also inside the application image, since the Dockerfile
copies `app` and `.dockerignore` does not exclude it.

## Decision

1. **Numbered SQL migrations and a small runner.** Migrations are
   files applied in order by a runner written on psycopg, which is
   already a dependency. No migration framework is added. The code
   uses raw psycopg with no ORM, and there are no models for a
   framework to read.

2. **A `schema_migrations` table records what ran.** It holds the
   version, the file name, a SHA-256 checksum and the time applied.
   Each run recomputes the checksum of every applied file. A mismatch
   stops the run, because an edited migration means databases no
   longer agree on what a version contains.

3. **One runner at a time.** The runner holds a Postgres advisory
   lock on a dedicated connection for the whole run. Two instances
   started together serialize, and the second finds nothing to do.

4. **Atomicity differs for the baseline.** Migration 0001 is the
   current `schema.sql`, unchanged. It manages its own transactions,
   so it runs outside a runner transaction and its version row is
   written after it succeeds. The file is idempotent, so a run that
   stops before the row is written is repaired by running again.
   Every later migration runs in one transaction together with its
   own version row, so a failed upgrade leaves the previous schema
   and no row. A later migration must not contain transaction
   control of its own.

5. **A command applies migrations, not the application.** The runner
   is a separate step in a deployment. Compose gets a one-shot
   service that runs it, and the `neuromesh` service waits for that
   service to complete. A rollout decides when the schema changes.

6. **The application checks and refuses.** At startup, once the pool
   is up, the application compares the applied versions with the
   highest version in the image. If the database is behind, or a
   recorded checksum differs from the bundled file, the process exits
   with a message naming what is missing. A database that is ahead of
   the image is allowed, which is what a rollback of the code
   produces.

7. **Add before remove.** A migration must work with the code that is
   running when it is applied, so it can go first in a rollout and a
   rollback of the code never meets a schema it cannot use. A
   destructive change ships in a later migration, after no release
   depends on the old shape.

8. **SQLite is unchanged.** It keeps upgrading itself in its
   repository constructors.

## Consequences

- Once 0001 is applied, its file is frozen. Editing it breaks its
  checksum on every migrated database, so every later schema change
  is a new numbered file, and `schema.sql` stops being a description
  of the current schema. The schema is read from the whole set.
- The tests that read `schema.sql` directly, the default tenant tests
  and the upgrade tests, will read the migration set instead.
- CI and the README move from `psql -f` to the runner. CI then takes
  the same path a deployment takes, which it does not today.
- The change adds a table, a lock and a failure mode. An application
  that starts against a database that is behind now exits with a
  clear error, where before it started and failed on writes.
- Which database role runs migrations and which role the application
  uses is not decided here. A migrator that owns the schema and a
  runtime role limited to data access is a separate ADR.

## Alternatives Considered

**Apply the idempotent file on every deploy.** Rejected. It records
nothing, it cannot run a data change exactly once, and the file would
have to keep a guard for every earlier state of the database as it
grows.

**Alembic.** Rejected. It is built on SQLAlchemy, which this code does
not use, and its autogeneration compares models this code does not
have. Hand-written migrations would give the same result as the
runner above with a dependency tree on top.

**Let the application migrate on every start.** Rejected. Concurrent
starts would race, a rollout could not decide when the schema
changes, and the application process would need the right to change
the schema while it serves traffic.

## Open questions

- Where the migration files live, and whether the baseline is a move
  of `schema.sql` or a copy. A move leaves one source of truth and
  changes every reference to the old path (compose, CI, the README and
  the schema tests). A copy leaves two files that can drift. This is
  decided in the baseline pull request, after the references are
  counted.
- Whether to keep the compose init mount once the migrate step
  exists. It would be a second way to reach the same result.
- The name and location of the runner command.

## Follow-ups

Implementation, in order, each as its own pull request:

- The runner and its tests, wired to nothing, so runtime behavior does
  not change. Planned tests: an edited applied file is refused, two
  runners at once serialize, and a failing later migration leaves
  nothing applied.
- The baseline migration, tested by adopting it from an empty
  database, from the frozen pre-tenancy schema and from the current
  schema, and by running it twice.
- The compose step, CI and the README on the runner, and the startup
  check, tested against a database that is behind.
- A separate ADR for the migration role and the runtime role.

## Progress

2026-10-14. The Status line above was written before any code. Since
then the runner (#343), the baseline migration (#344) and the command
(#345) have merged. The startup check in Decision 6 has not.

The compose and CI step is in progress on its own branch:

- Compose has a one-shot `migrate` service, and `neuromesh` waits for
  it with `service_completed_successfully`. The Postgres init mount is
  removed, which answers the second open question: the runner is the
  only route to a schema in compose.
- `migrate` and `neuromesh` run one image, tagged `neuromesh-app:local`,
  and `migrate` never pulls it. `docker compose up --build` builds it
  first. Running `migrate` alone on a machine that has not built the
  image fails.
- Both CI jobs, and the README test setup, apply the schema with the
  runner instead of `psql -f`.
- Because the startup check is not in yet, nothing in the application
  looks at the schema. The wait for `migrate` exists only in compose.

Evidence from running it:

- A volume created by the old init script held seven tables with rows
  and was behind the code: `jobs` had neither `execution_timeout_seconds`
  nor `tenant_id`. The baseline brought it up to date in place. Row
  counts were unchanged, and a dump taken before and after differed only
  in the new columns, keys, index and `schema_migrations`. A second run
  printed "nothing to apply".
- With a database name that does not exist, `migrate` exits 1 and the
  application container is created but never started.
- The runner connects with a password inside the URL, which is how CI
  passes it, and refuses a wrong password.

Not shown yet: that the hardening workflow goes red when each property
of `migrate` is broken on a throwaway branch, as ADR 0061 did for the
application container.

2026-10-14, the runner and a rollback. Decision 6 allows a database that
is ahead of the image, and Decision 7 depends on it. The runner did not.
Run against a database that recorded a version the image has no file
for, it exited 1 with "recorded as applied but has no file in the
migration set". In compose the `migrate` service would then fail after a
rollback of the code, and `neuromesh` waits for it to complete, so the
application would not start. This was reproduced on a scratch database
before anything was changed.

The runner now compares the recorded history with the migration set in
one function that touches no database, and the startup check will call
the same function:

- A recorded version above the highest version in the image is accepted.
  Nothing is applied and nothing in the history changes.
- A hole in the recorded versions, a recorded version below the highest
  that has no file, and a changed checksum are still refused.
- An image that carries no migrations is refused when the database has a
  history, so a broken build cannot start silently.

Accepting a database that is ahead removes a check that happened to
stop an older image from running on a newer schema. What replaces it is
Decision 7, which is a convention and not a mechanism. A migration that
removes or renames something would still break a rolled-back image, and
nothing here detects that.

Run against the scratch database again, the runner printed "nothing to
apply", exited 0 and left the recorded history as it was. Ruff is clean
and 802 tests pass. The rollback has not been run through compose, and
the startup check is still not in.
