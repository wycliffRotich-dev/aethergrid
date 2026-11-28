# ADR 0110: Accept the Tables the Upgrade Creates in the Rehearsal

## Status

Proposed. The upgrade rehearsal accepts a table that the upgrade creates
when the table is empty, prints its name, and still fails on a table that
arrives with rows, on a dropped table and on every change it named before.

Related: ADR 0085, ADR 0087, ADR 0098, ADR 0107, ADR 0108.

## Context

The rehearsal exports every table before the upgrade and again after it, and
compare_snapshots compares the two exports (ADR 0085). A table that is in
the second export and not in the first is named as a difference, with the
line: missing from the before snapshot.

That was right while every upgrade changed tables that already existed.
Migration 0005 created none. Migrations 0007, 0008 and 0009 each create one:
public_demo_scope, lease_reclaims and lease_refusals. A rehearsal from
v0.7.0, whose migrations end at 0005, to a commit that carries them would
end at the comparison, after the images are built and the cluster is seeded,
and it would name three tables that the upgrade is meant to create.

No migration from 0006 to 0010 inserts a row, so a table that they create is
empty after the upgrade. The rows the rehearsal seeds go into tables that
exist before it.

The line after a successful comparison counts the tables of the second
export, so a created table would be counted as one that did not change.

## Decision

1. A table that is in the export after the upgrade and not in the export
   before it is a table the upgrade created. When it holds no rows it is not
   a difference, and compare_snapshots skips it.
2. A created table that holds rows is a difference. It is named with its row
   count, in the form: table: created by the upgrade, rows: N. The
   migrations create these tables empty, so rows in one mean the upgrade
   wrote data, and decision 4 of ADR 0085 says such a finding is recorded
   and not hidden.
3. A table in the export before the upgrade and not in the export after it
   stays a difference, as does every change that compare_snapshots names
   today. An export of a created table that has no header, or that repeats
   an id, is an error, as it is for any other table.
4. created_tables(before, after) returns the names of the tables the upgrade
   created, in order. The rehearsal prints one line for each after the
   comparison succeeds, so a created table is shown and not passed over.
5. The line after a successful comparison counts the tables of the export
   before the upgrade. It counted the tables of the export after it, which
   would count a created table as one that did not change.
6. The one test that pinned the line for a table missing from the before
   snapshot changes in the same commit as the code, and nine tests are
   written first.

## Consequences

A rehearsal across a release that adds tables can finish. The rows of every
table that exists before the upgrade are compared as before.

A later migration that fills a table it creates makes the rehearsal fail
with the name of the table and its row count, and that finding is recorded,
as decision 2 says.

## Alternatives Considered

- **Ignore the tables that exist only after the upgrade.** Rejected. A table
  that arrives with rows would pass unseen, and the comparison would stop
  covering part of the upgrade.
- **Keep a list of the expected new tables in the script.** Rejected. The
  list would change with every migration that adds a table, and a stale list
  would fail a correct run or pass a wrong one.
- **Rehearse only between releases that have the same tables.** Rejected.
  Every release that adds a table would then go out with no rehearsal.

Not claimed: safe to expose.

## Progress

2026-11-28. Written before any code. compare_snapshots names a table that is
only in the export after the upgrade as a difference, and the line after a
successful comparison counts the tables of the export after the upgrade.

Not claimed: safe to expose.

2026-11-28. Built and tested. compare_snapshots reads a table that is only
in the export after the upgrade with the same _read as every other table. It
skips the table when it holds no rows and names it as "<table>: created by
the upgrade, rows: N" when it holds some. A header that is missing or an id
that repeats still raises. A dropped table and every other difference named
before stay differences. The new function created_tables(before, after)
returns the sorted names of the tables that are only in the export after.
main() prints one line, "the upgrade created the table <name>", for each of
them after the success line, and the success line counts the tables of the
export before the upgrade.

Tests. The compare file went from 7 to 15 tests. The test that pinned
"missing from the before snapshot" was replaced in the same commit by a test
for a table missing from the after snapshot, and eight tests were added for
created tables. The sequence file went from 4 to 8 tests. Its wire helper
takes an optional export for the second read, and four tests of main() cover
the success line, the created lines in order, a created table with rows
ending the run at the comparison, and a run with no created table printing
no created line. Decision 6 counted nine tests written first and did not
name these four. Before the code was written 8 of the 15 compare tests and 3
of the 8 sequence tests failed. After it, tests/scripts passed with 302
tests and tests/architecture with 60.

Mutation check. Eleven breaks of scripts/upgrade_rehearsal.py were run
against all of tests/scripts, and each turned tests red as predicted. The
failing cases were:

- a created table not read: 4
- the test for rows inverted: 6
- the row count one too high: 2
- the created line reworded: 2
- the continue after the created branch removed: 6
- created_tables returning every table of the export after: 5
- created_tables sorted in reverse: 2
- created_tables subtracting the wrong way round: 3
- the success line counting the export after: 2
- the print of each created table removed: 1
- the dropped table branch disabled: 2

That is 35 failing cases in all. No break survived. The script was restored
byte for byte after the run.

Not claimed: safe to expose.
