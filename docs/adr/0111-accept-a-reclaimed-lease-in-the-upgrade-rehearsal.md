# ADR 0111: Accept a Reclaimed Lease in the Upgrade Rehearsal

## Status

Accepted. The upgrade rehearsal accepts a worker that holds nothing after
the new API starts when the database holds a reclaim record for the seeded
job and the seeded worker. It still fails on every other worker body.

Related: ADR 0085, ADR 0088, ADR 0089, ADR 0107, ADR 0110.

## Context

After the migrations and the schema comparison, the rehearsal starts the
API of the new release on the upgraded database and reads the seeded node,
worker and job through it (ADR 0088). Since ADR 0089 it also requires the
worker body to show the seeded job with the seeded command.

The first real rehearsal from v0.7.0 to efaf3d6, the commit that carries
migrations 0006 to 0010, passed every step up to the new API. The
migrations applied, the upgrade changed nothing in seven tables, the three
new tables were created, and the upgraded schema matched a fresh one. The
run then ended at the read back: GET /workers/{id} returned no running
job. The node and job reads passed.

The seed was written at 10:38:39 and the read was made at 10:40:18, 99
seconds later. A lease lasts 30 seconds, and nothing renews it once the
old API has stopped, because an agent manages the seeded worker and none
is started. The new API started at 10:40:10, so the lease was more than 30
seconds old by then. The new API runs reconciliation once a second, and
RecoverExpiredLeaseService reclaims a job whose lease has expired: it
deletes the lease, recovers the worker, which clears its running job,
reclaims the job and records the reclaim (ADR 0107).

ADR 0089 decision 4 says that if a real run shows the new API reclaiming
the lease before the read, the finding is recorded and the decision
revisited, and that the check is not weakened to pass. A worker with no
running job is the state that a reclaim leaves, so this ADR records it and
revisits the decision.

The seeded job has max_retries 0, which is the default, because the create
request has no field for it. A reclaim therefore fails the job, and it is
never assigned again. After the new API starts, the worker either holds
the seeded job or holds nothing.

A reclaim record does not depend on the clock. For an upgrade that creates
the table lease_reclaims, the rehearsal already requires it to be empty
after the upgrade (ADR 0110), so a row that appears later was written by
the new API.

## Decision

1. After the three reads, a worker body that has a running_job is checked
   as before. The job must carry the seeded command, and a different
   command ends the run.

2. A worker body with no running_job is accepted when lease_reclaims holds
   a row whose job_id and worker_id are the seeded ones. Any other worker
   body, including one with no running_job and no such row, ends the run.

3. The row is waited for, because the new API recovers the worker before
   it records the reclaim (ADR 0107, decision 5). The wait uses wait_until
   and is bounded at 10 seconds. When it times out, the run ends with: GET
   /workers/{id} returned no running job and no reclaim record.

4. The row is read through psql in the database container with one fixed
   statement that counts the rows for the two ids. Each id is parsed as a
   UUID first, and the statement is built only from the parsed values, so
   a value that is not a UUID is an error and never reaches the database.
   An answer that is not a single count is an error, not false.

5. read_back keeps its two positional arguments and takes a keyword-only
   argument, reclaimed, a function that returns true when the record
   exists. Without it the check of ADR 0089 stays as it was. main passes
   it, using the compose that reaches the upgraded database.

6. The six wirings of read_back in tests/scripts that replace it accept
   the new argument, and they change in the same commit as the code. The
   tests that call read_back without reclaimed stay as they are.

7. ADR 0089 gets a dated entry that revisits its decision 4 in the way
   that decision says.

## Consequences

A rehearsal no longer depends on how long the build takes between the seed
and the read. A worker that kept the job and a worker whose lease was
reclaimed both pass, and a worker that lost its job without a record
fails.

The database is read only when the worker holds nothing, so a run that
reads before the lease expires does not touch it. The command is still
compared on the path that holds the job, and a command is never printed.

## Alternatives Considered

- **Build the new image before the old stack is seeded.** Rejected. It
  shortens the gap and still races a 30 second lease, so a slow machine
  would fail a correct upgrade.

- **Renew the lease while the old API is stopped.** Rejected. A renew
  needs a running agent and an API to serve it, and neither exists in the
  gap between the two releases.

- **Add a switch that stops the cluster loop.** Rejected. It changes the
  product so that a test passes, and the rehearsal would no longer run the
  new release as it runs.

- **Drop the running_job check.** Rejected. A worker that lost its job in
  the upgrade would pass unseen.

Not claimed: safe to expose.

## Progress

2026-11-28. Written before any code. The first real rehearsal from v0.7.0
to efaf3d6 ended at the read back with GET /workers/{id} returned no
running job, 99 seconds after the seed, with a lease that lasts 30
seconds. The tests that pin the check are written next.

Not claimed: safe to expose.

2026-11-28. Built and tested. read_back takes the keyword arguments
reclaimed, clock and sleep. A worker body with a running_job is checked as
before. A body with none is accepted when reclaim_recorded finds a row in
lease_reclaims for the seeded job and worker. The row is waited for up to
10 seconds, in steps of 0.5 seconds. Without a row the run ends with: GET
/workers/{id} returned no running job and no reclaim record. reclaim_sql
parses each id as a UUID and writes it in canonical form, and
parse_reclaim_count reads one ASCII count and raises on anything else.
main passes reclaimed, built on the compose of the old side, which reaches
the upgraded database.

Tests. tests/scripts/test_upgrade_rehearsal_reclaim.py has 38 tests. 36
were written before the code and failed, all 36. Two were added after a
review of the count parser found that no test sent a digit outside ASCII.
One test of main() was added to the new_api file, which pins that main
passes reclaimed and that it reads through the old side. Six fakes of
read_back changed in the same commit so that they accept the new
arguments. tests/scripts passed with 341 tests.

Mutation check. 24 breaks of scripts/upgrade_rehearsal.py were run against
all of tests/scripts, and each turned tests red as predicted. The failing
cases were:

- ids not parsed to canonical form: 11
- job id label swapped: 4
- bad id handler removed: 8
- ids swapped in the statement: 5
- worker condition dropped: 5
- table renamed: 5
- count above or equal to zero: 2
- count equal to one: 1
- ASCII guard removed: 2
- digit guard removed: 6
- count error text reworded: 8
- query label reworded: 1
- record ignored: 1
- timeout cut to 5 seconds: 1
- wait timeout set to 0: 2
- timeout handler narrowed: 2
- timeout handler widened: 1
- reclaimed test inverted: 7
- strict message returns None: 2
- no record text reworded: 2
- success path returns a problem: 2
- route drops reclaimed: 5
- main passes None: 1
- main uses the new compose: 1

That is 85 failing cases in all. No break survived. The script was
restored byte for byte after the run.

Not claimed: safe to expose.

2026-11-28. The rehearsal now says which way the worker check passed. The
first real rerun on efaf3d6 passed. It read the worker about 35 seconds
after the seed, against a lease of 30 seconds, and its output did not say
whether the worker still held the job or held nothing and the reclaim
record was found.

read_back returns held when the worker still holds the job with the seeded
command, and reclaimed when it held nothing and the record was found. main
prints one line before the success line: "the seeded worker still held the
job with the seeded command" or "the seeded worker held nothing and its
reclaim record was found". A run that fails prints neither.

Tests. 9 tests were added: 4 in the reclaim file, for the value read_back
returns, and 5 in the new_api file, for the lines main prints, their order
against the success line, and a failed read that prints no outcome line. 8
of them failed before the code. The ninth passed on the old code and is
covered by a break below. The fakes of read_back in tests/scripts return
an outcome and changed in the same commit as the code. tests/scripts
passed with 350 tests.

Mutation check. 12 breaks of scripts/upgrade_rehearsal.py were run against
all of tests/scripts, and each turned tests red as predicted. The failing
cases were:

- held line reworded: 2
- reclaimed line reworded: 2
- main always prints the held line: 2
- outcome line not printed: 4
- outcome line printed after the success line: 2
- held line printed before the read: 2
- read_back always returns held: 2
- read_back always returns reclaimed: 2
- held test inverted: 4
- held always true: 2
- held always false: 2
- worker_check drops reclaimed: 7

That is 33 failing cases in all. No break survived. The script was
restored byte for byte after the run.

Not claimed: safe to expose.

2026-11-28. Status changed to Accepted. The real upgrade rehearsal ran
from v0.7.0 to efaf3d6 with the script from 8894fb4 and passed in 95
seconds. It read the seeded worker 35 seconds after the seed, against a
lease of 30 seconds, and printed "the seeded worker held nothing and its
reclaim record was found".

So the pass came by the reclaim path: the worker held nothing and the
database held a reclaim record for the seeded job and the seeded worker.
The new API then served the seeded node, worker and job, and no container,
volume or network was left behind. The first rerun on efaf3d6, before the
outcome line existed, also passed, and its output did not say which way.

Not claimed: safe to expose.
