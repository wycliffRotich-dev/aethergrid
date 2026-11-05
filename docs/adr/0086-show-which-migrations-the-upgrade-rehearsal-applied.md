# ADR 0086: Show Which Migrations the Upgrade Rehearsal Applied

## Status

Proposed. It becomes Accepted when the rehearsal reads
`schema_migrations` before and after the migrate run, prints the
versions the run added, and fails when it added none, when an applied
version is missing afterwards, and when the name or checksum of an
applied version changed. The tests are written first and each fails
for the right reason against the script on main. One real run from
v0.6.0 prints the versions it applied.

Related: ADR 0071, ADR 0072, ADR 0074, ADR 0075 (condition 5) and
ADR 0085.

## Context

ADR 0085 finished the rehearsal: it seeds a database with the old
release, runs only the new release's migrate service and compares every
table before and after. The comparison leaves out `schema_migrations`,
which changes on every upgrade by design.

That leaves one claim unobserved. A run in which migrate applied
nothing prints "the upgrade changed nothing in 7 tables" and exits 0,
exactly as a run does in which 0005 was applied and kept every row.
The output cannot tell the two apart. ADR 0085 says so in its Not
Claimed section: that 0005 was applied rests on v0.6.0 carrying 0004
only and main carrying 0005, and printing the applied versions is
listed there as a follow-up.

Two runs would pass while proving nothing: one where `--old` already
carries the migration under test, and one where migrate exits 0
without recording a version. Neither is caught today.

## Decision

1. The script reads `SELECT version, name, checksum FROM
   schema_migrations ORDER BY version` twice, through the same psql
   path as the table exports: after the before export, and after the
   migrate run.
2. A pure function compares the two lists and returns one line per
   problem: an applied version missing afterwards, a changed name or
   checksum, and no version added.
3. The run prints the versions the upgrade added, one per line, and
   ends with an error that names every problem found.
4. A run that adds no version fails. A rehearsal that applies nothing
   is not an upgrade rehearsal. If a legitimate no-op run appears, it
   gets its own flag in its own ADR. None is added now.
5. `schema_migrations` stays out of the table comparison.

## Consequences

- The sentence "0005 was applied" in a rehearsal report is observed,
  not inferred from two release contents.
- A run from the same commit on both sides now fails instead of
  passing.
- The rehearsal reads one more table twice, which costs milliseconds.

## Not Claimed

- That a migration changed the schema as intended. A version recorded
  in `schema_migrations` shows the runner ran it, not that its SQL did
  what its author meant. Constraints, indexes and defaults are the
  catalog check in the Follow-ups.
- That the recorded checksum matches the migration file on disk. The
  script compares the recorded values before and after, and does not
  read files.
- That a run from a commit satisfies condition 5 of ADR 0075. That
  needs a release that carries 0005.

## Alternatives Considered

- **Include `schema_migrations` in the table comparison and allow the
  new rows.** Rejected. It mixes the check that data was preserved
  with the check that migrations ran, and the allowance rule would
  have to know which rows are expected.
- **Read what migrate printed.** Rejected. Its output is not a
  contract, and a log line cannot show what was recorded.
- **Hash the migration files.** Rejected. ADR 0074 already pins their
  checksums, and the question here is what the database recorded.

## Follow-ups

- A catalog check after the upgrade for constraints, indexes, defaults
  and sequences (ADR 0085, Not Claimed).

## How to Verify

```bash
grep -c "applied_migrations" scripts/upgrade_rehearsal.py
```

It prints 0 while this ADR is a proposal.

## Progress

Nothing is merged. This ADR is a proposal.
