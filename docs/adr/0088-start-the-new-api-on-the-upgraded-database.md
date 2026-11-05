# ADR 0088: Start the New API on the Upgraded Database

## Status

Proposed. It becomes Accepted when the rehearsal starts the new
release's API on the upgraded database, reads back the seeded node,
worker and job with the key the old release issued, and fails when the
API does not start, when a read is not a 200 and when a body carries a
different id. The tests are written first and each fails for the right
reason against the script on main. One real run from v0.6.0 reads all
three back and stops the new API cleanly.

Related: ADR 0064, ADR 0072, ADR 0075 (condition 5), ADR 0085, ADR 0086
and ADR 0087.

## Context

The rehearsal now builds the new release, migrates a seeded database,
compares every row, shows the applied versions and compares the schema
with a fresh install. ADR 0085 lists what that leaves out, and one item
is that the new API starts and serves the migrated data.

A database can be correct and still be unusable by the release that
upgraded it. The new API checks the schema version before its cluster
loop starts (ADR 0072), and tenant scoping (ADR 0064) can make a row
invisible to a key that was valid before the upgrade. Neither is
exercised by anything the rehearsal does today.

The seed is written through the old release's API with a key issued for
DEFAULT_TENANT_ID. The worker is managed by an agent, so the in-process
tick never runs the job. The responses of GET /nodes/{id},
/workers/{id} and /jobs/{id} each carry a top-level `id`.

## Decision

1. After the schema comparison, the script starts the neuromesh service
   of the new release with `up -d --no-deps --no-build --wait`, on the
   image the earlier build step made. A container that stops during its
   startup check, or does not become healthy, ends the run.
2. It reads the seeded node, worker and job with GET /nodes/{id},
   /workers/{id} and /jobs/{id}, using the key the old release issued
   for the default tenant. Each read must return 200 and a body whose
   `id` is the seeded id.
3. A read that does not, ends the run, and the message names the route,
   the status and the id that was expected. A body is never printed,
   because a body may hold data.
4. The rule that the key is sent only to the loopback address has one
   copy. `http_post` and the new `http_get` both use it.
5. The script stops the new API afterwards and checks how it ended, as
   it does for the old one.
6. No status, lease or running job is asserted. The new API starts a
   cluster loop, and it may reclaim a lease that nothing renewed since
   the old release stopped, which is correct behavior and changes state.

## Consequences

- A release that upgrades a database and then cannot start on it, or
  cannot see the rows it upgraded, fails the rehearsal.
- That a key issued before the upgrade still authenticates, and still
  resolves to the same tenant, is observed.
- A run gains a container start, three reads and a stop.

## Not Claimed

- That any state is preserved. Statuses may change on startup by
  design, and the reads assert existence and identity only.
- That the other routes work, or that the job's command is intact,
  since the job response leaves it out by design (ADR 0020).
- That a tenant field is correct. The worker response carries none, and
  the check is that a read with a default-tenant key finds the row.
- Behavior under load, or after more than one start.
- That a run from a commit satisfies condition 5 of ADR 0075.
- That the check works from an old release other than v0.6.0.

## Alternatives Considered

- **Issue a new key on the new release.** Rejected. It would not show
  that a key from before the upgrade still resolves.
- **Start the whole stack with `up -d --wait`.** Rejected. It would
  recreate postgres and rebuild images, which this run shares through
  one project name, and `--no-deps --no-build` starts only what the
  earlier stages built.
- **Assert the worker's status and the lease.** Rejected for decision
  6. It would fail on correct reconciliation.

## Follow-ups

- Read the job's command through the worker route, which is the only
  read that returns it.

## How to Verify

```bash
grep -c "http_get" scripts/upgrade_rehearsal.py
```

It prints 0 while this ADR is a proposal.

## Progress

2026-11-05. Written before any code. main() ends after the schema
comparison, so the new API is never started on the upgraded database.
