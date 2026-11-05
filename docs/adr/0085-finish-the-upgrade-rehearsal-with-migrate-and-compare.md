# ADR 0085: Finish the Upgrade Rehearsal With Migrate and Compare

## Status

Proposed. It becomes Accepted when the rehearsal script applies the new
release's migrations to the seeded database, exports every table again
and fails on any difference, with tests that failed for the right reason
before the code was written, and when one real run from v0.6.0 is
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
