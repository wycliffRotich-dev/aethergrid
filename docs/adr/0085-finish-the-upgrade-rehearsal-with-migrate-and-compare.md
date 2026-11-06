# ADR 0085: Finish the Upgrade Rehearsal With Migrate and Compare

## Status

Accepted. It was Proposed until the rehearsal script applies the new
release's migrations to the seeded database, exports every table again
and fails on any difference, with tests that failed for the right reason
before the code was written, and one real run from v0.6.0 was
recorded in the Progress section with what it printed.

Related: ADR 0071 (the migrate service) and ADR 0075 (condition 5).

## Context

ADR 0075 stays Proposed because no database upgraded from v0.6.0 has
been run through migration 0005. Hand rehearsals were run on a scratch
database, and `scripts/upgrade_rehearsal.py` was merged so that the run
can be repeated. No ADR names that script.

What main does today, read from the script at 4780e3f:

1. It exports the old and the new ref with `git archive`, makes a
   throwaway database secret, picks free ports and writes a compose
   override. Both sides use one compose project, so they share one
   database volume, and the override names each image by
   `REHEARSAL_SIDE`.
2. `main()` builds and starts the old release, issues an API key, seeds
   a node, a worker and a job through the API, waits for the cluster to
   come to rest, stops the old API, exports every table and checks that
   each required table has rows. Then it returns 0.
3. `snapshot` and `compare_snapshots` exist and have tests.
   `schema_migrations` is left out of the export because it changes on
   every upgrade by design.

A run today therefore exits 0 having upgraded nothing and compared
nothing. The name of the script is ahead of what it does.

## Decision

1. After the seed check, the rehearsal runs only the `migrate` service
   of the new side, against the same compose project and so the same
   database. It does not start the `neuromesh` service of the new side.
   The old API is already stopped, so nothing writes to the database
   between the two exports except the migration.
2. A failed `migrate` ends the run with its output and takes no second
   export. The refusal of migration 0005 for rows that cross tenants
   (#419) is then a result of the rehearsal and not noise.
3. After a successful `migrate`, the rehearsal exports again with the
   same function and compares the two exports with `compare_snapshots`.
   Any difference ends the run with a non-zero status and each
   difference is printed. No difference is filtered out.
4. The expected result from v0.6.0 to a commit that carries 0005 is no
   difference, because the writers of v0.6.0 already fill the tenant
   (ADR 0075, slice 1) and the backfill has nothing to change. That is
   a prediction. If the first real run shows a difference, it is
   recorded as found, with the row, and is not hidden by an exemption.
5. The order of the stages is pinned by tests that extend
   `tests/scripts/test_upgrade_rehearsal_sequence.py`, written first.
   One of them fails if the `neuromesh` service of the new side is ever
   started.

## Not Claimed

- That a run with `--new` set to a commit satisfies condition 5 of ADR
  0075. That condition needs a release that carries 0005, and no tag
  does yet. A run from a commit is evidence that the mechanism works.
- That the constraint changes are checked. NOT NULL, the dropped keys
  and the composite keys cannot be seen in a CSV export of the rows.
  `test_workers_leases_schema_catalog.py` covers them on the test
  database, and a catalog check after the upgrade is a follow-up.
- That the new API starts and serves the migrated data. That is a
  later stage.
- That the export compares everything. It holds rows and column names,
  not indexes, defaults or sequences.
- How long 0005 takes on a real table. The seed holds a few rows, and
  ADR 0075 already says nothing has been measured.

## Alternatives Considered

- **Start the whole new stack with `up`.** Rejected. The new API runs a
  scheduler and workers send heartbeats, so rows could change between
  the two exports and the comparison would measure the API along with
  the migration.
- **Run the migrations from the host with
  `python -m app.infrastructure.migrations`.** Rejected. The rehearsal
  is about the image that would be released, and that image applies
  its migrations through its own `migrate` service (ADR 0071).
- **Compare row counts only.** Rejected. A count does not show a tenant
  that changed or a column that was dropped.

## Consequences

- A run of the script upgrades the seeded database and fails on any
  change to rows or columns, so the word rehearsal is true of it.
- A real tag is still needed before ADR 0075 can be accepted, and this
  ADR does not change that.
- The first run against v0.6.0 may show a difference nobody predicted.
  That is the point of running it.

## Progress

2026-11-05. Written before any code. `main()` still returns after the
seed check, so nothing is migrated or compared yet.

2026-11-05. The two stages are written. After the seed check, main()
builds the neuromesh image of the new side, runs only the migrate
service there with run --rm --no-deps, exports the tables again with the
same function and fails on any difference, naming each one. The build
is a step of its own because the migrate service names an image and has
no build section. --no-deps keeps compose from recreating postgres,
which both sides share through one project name.

The tests were written first. Five failed for the reasons expected: the
new side had no commands, there was no second export, a failed migrate
and a changed row did not raise, and the extended order test was missing
five steps. Two mutations each failed the tests. Starting the new side
with up -d --wait failed 3, and disabling the difference check failed 1.
The file was restored and compared byte for byte. tests/scripts passes
(186), ruff is clean, and mypy as CI runs it reports no issues in 237
source files.

One real run, on 2026-11-05, from v0.6.0 to main at 0655914. It seeded
one node, one worker and one job, exported 7 tables before and after,
and printed "the upgrade changed nothing in 7 tables". It printed no
report of leftovers. By the stage times the run took 4 minutes 21
seconds: 3 minutes 14 seconds to build and start the old release, 57
seconds to build the new one, and about 4 seconds for migrate and the
second export. That is one run and not a measurement.

Not shown by that run. That 0005 was applied: the export leaves
schema_migrations out and the script does not print what migrate
applied, so the claim rests on v0.6.0 carrying 0004 only and main
carrying 0005. Printing the applied versions before and after is a
follow-up. The constraint changes, which a table export cannot show.
Condition 5 of ADR 0075, because the run was from a commit and no tag
carries 0005. How long 0005 takes on a real table.

2026-11-05. The follow-up about printing the applied versions is done
in ADR 0086. The rehearsal now reads schema_migrations before and
after the migrate run and prints each version the upgrade added, and a
real run from v0.6.0 printed 0005. The follow-up about the constraint
changes, which a table export cannot show, is done in ADR 0087. That the new API starts and
serves the migrated data is done in ADR 0088.
