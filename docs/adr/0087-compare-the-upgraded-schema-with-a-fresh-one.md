# ADR 0087: Compare the Upgraded Schema With a Fresh One

## Status

Accepted. It was Proposed until the rehearsal built a second
database with the new release's migrate service, dumped the schema of
the upgraded database and of the new one with pg_dump --schema-only,
ignored the two kinds of line that carry a random key, failed on every
other difference and named each one, and failed on a dump with no table
in it. The tests were written first and all 19 failed for the reasons
expected against the script on main. One real run from v0.6.0 reported
a match and no leftovers.

Related: ADR 0071, ADR 0074, ADR 0075 (condition 5), ADR 0085 and
ADR 0086.

## Context

The rehearsal compares the rows of every table before and after the
upgrade and, since ADR 0086, shows which migrations were applied. ADR
0085 says what that leaves out: NOT NULL, the dropped keys, the
composite keys, indexes, defaults and sequences cannot be seen in a CSV
export of rows, and a catalog check after the upgrade is a follow-up.

`tests/infrastructure/test_workers_leases_schema_catalog.py` asks a
freshly migrated database whether it enforces four foreign keys and two
NOT NULL columns. It covers what its author listed, on a database
built from nothing, and says nothing about a database that was
upgraded.

A probe on 2026-11-05 on the compose stack, with PostgreSQL 16.15 from
the image that compose pins, built two databases from nothing with the
same five migrations and dumped each with `pg_dump --schema-only
--no-owner`. Both dumps had 454 lines. They differed in two lines, the
`\restrict` and `\unrestrict` commands that pg_dump writes with a
random key. The migrate service accepted a different
`NEUROMESH_DATABASE_URL` through `docker compose run -e` and applied
all five migrations to the new database. A case-insensitive search of
the five migration files for CREATE FUNCTION, TRIGGER, VIEW, TYPE and
EXTENSION found none.

## Decision

1. After the table comparison passes, the script creates the database
   schema_fresh in the run's own Postgres and runs only the new
   release's migrate service against it, with --no-deps and
   NEUROMESH_DATABASE_URL pointing at that database, as the probe did.
2. It dumps the upgraded database and schema_fresh with pg_dump
   --schema-only --no-owner, in the same container.
3. A pure function drops every line that starts with `\restrict ` or
   `\unrestrict `, which carry a random key and nothing else, and
   compares what is left line by line, in order. It returns one line
   per difference and says which side the line is only in.
4. A dump with no line that starts with CREATE TABLE ends the run, so
   two empty dumps cannot pass by being equal.
5. Any difference ends the run with every difference named. A match
   prints the number of lines compared.
6. The script does not drop schema_fresh. It lives in the run's own
   Postgres, which the run's teardown removes, and the leftover check
   reports anything that stays.

## Consequences

- The claim that the upgraded database has the same schema as a fresh
  install of the same release is observed, not assumed.
- The properties the catalog test checks on a fresh database are
  therefore shown to hold on the upgraded one too, for as long as that
  test passes on the same commit.
- A migration whose effect on rows it finds differs from its effect on
  an empty database now fails the rehearsal.
- A run gains one database, one migrate run and two dumps. Their time
  is read from the stage times of the real run.

## Evidence

- The 19 new tests in
  `tests/scripts/test_upgrade_rehearsal_schema.py` were written first.
  All 19 failed against the script on main: 14 with AttributeError
  because `compare_schemas`, `schema_lines`, `schema_dump` and
  `fresh_schema` did not exist, 2 with DID NOT RAISE, 1 for a missing
  line of output and 1 for a missing stage line.
- Six mutations each fail the new tests, and the script was restored
  and compared byte for byte afterwards: removing the no-table check
  fails 5, treating every line as equal fails 6, keeping the random-key
  lines fails 9, disabling the guard in `main()` fails 2, running the
  fresh migrate against the upgraded database fails 1, and dumping the
  upgraded database as the fresh one fails 1.
- `tests/scripts` passes (219, up from 200), ruff is clean and strict
  mypy reports no issues in 239 source files. The full suite passes
  (1237, up from 1218).
- One real run, `python scripts/upgrade_rehearsal.py --old v0.6.0
  --new HEAD`, ended with `the upgraded schema matches a fresh one
  (452 lines)` after `the upgrade changed nothing in 7 tables`, and
  printed no report of leftovers. The 452 lines are the 454 of the
  probe without the two lines that carry a random key. From the stage
  times, building the fresh database, dumping and comparing took 4
  seconds. That is one run and not a measurement.

## Not Claimed

- That the schema is right. It is shown to match a fresh install of the
  same files, not to be what the author intended.
- That a defect in the migration SQL is found. Both builds run the same
  files in the same order, so such a defect appears in both.
- That data is compared. The table export does that, and a schema-only
  dump holds no sequence values.
- That roles, or anything outside the one database, is compared.
- That the dump format is stable across PostgreSQL versions. The probe
  used 16.15, and compose pins the image by digest.
- That the check works from an old release other than v0.6.0.
- That a run from a commit satisfies condition 5 of ADR 0075.

## Alternatives Considered

- **A hand-written catalog query, as in the catalog test.** Rejected.
  It checks what its author lists, and pg_dump covers every object type
  by construction.
- **Compare information_schema.** Rejected. It does not hold indexes
  or the text of check constraints.
- **Pin the key with --restrict-key.** Not chosen. This note did not
  check that the option exists in the pinned image, and dropping two
  known line prefixes needs nothing from the version.

## Follow-ups

- Run the comparison from a tagged release once one carries 0005
  (ADR 0075, condition 5).

## How to Verify

```bash
grep -c "compare_schemas" scripts/upgrade_rehearsal.py
```

It printed 0 before this change and prints 1 or more now.

## Progress

2026-11-05. Written before any code. main() ends after the table
comparison, so the schema of an upgraded database is not compared with
anything.

2026-11-05. main() now builds schema_fresh with the new release's
migrate service, dumps both databases and compares them. The Evidence
section has the runs. The schema of an upgraded database is shown to
match a fresh install of the same release for one seed and one
release pair. Condition 5 of ADR 0075 is still open.

2026-11-08. The follow-up to run the comparison from a tagged
release is done. v0.7.0 is the first release that carries 0005, and
the rehearsal ran on its commit aa4eaca with v0.6.0 as the old
release and matched the schema (452 lines), as ADR 0075 records on
2026-11-06. Condition 5 of ADR 0075 is met.
