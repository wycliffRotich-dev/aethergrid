# ADR 0097: Create a Public Read Role That Can Do Nothing

## Status

Proposed.

Related: ADR 0071 and ADR 0094.

## Context

ADR 0094 says the public app is not deployed until it has a read-only
database role. The role has to exist before anything is granted to it,
and every grant needs its own review. A role that starts with no power
makes each later grant visible in the history.

A role belongs to the cluster and not to a schema. Two schemas in one
cluster share one role. The migration runner takes its lock per database,
so it does not serialise runners in different databases of one cluster.

## Decision

1. Migration 0006 creates the role aethergrid_public_read as NOLOGIN,
   NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION and NOBYPASSRLS.
2. The migration grants the role nothing. It has no privilege on any table
   and no USAGE or CREATE on any schema.
3. The role has no members and is a member of no role.
4. If the role already exists, the migration accepts it only when it has
   none of those attributes, holds no privilege, ownership or policy in
   this database or at cluster level, and has no membership in either
   direction. This is what lets a second schema in the same cluster apply
   the migration.
5. Otherwise the migration stops with an error that names the role and what
   it has. It does not change the role and it writes no version row.
6. If another runner creates the role between the check and the CREATE, the
   migration reads the role that runner created and applies the same
   checks to it.
7. It is a transactional migration, in one transaction together with its
   version row (ADR 0071, decision 4).

## Consequences

- The public app cannot connect with this role yet. It is a group role, and
  a login role that is a member of it is a later change.
- Every privilege the role gains later is a separate migration with its own
  ADR and its own tests.
- The check in decision 4 reads this database and the cluster level
  objects. Once a later change grants the role something in a database,
  this migration refuses to run against that database again.
- The checksum of 0006 is pinned in the frozen migrations test, so the file
  cannot be edited after it merges.

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That the role can read anything. It has no privilege at all.

## Alternatives Considered

- **Create the role by hand outside the migrations.** Rejected. A database
  built from the migrations would then differ from a deployed one, and no
  test could see it.
- **A role that can log in, created here.** Rejected. A migration cannot
  carry a password, and a login role with no password is a login role
  nobody has reviewed.
- **Grant SELECT on the public tables in the same migration.** Rejected.
  Each grant is a decision about what the public can see, and it should be
  reviewed on its own.

## How to Verify

    NEUROMESH_TEST_DATABASE_URL=postgresql://neuromesh@127.0.0.1:5433/neuromesh_test \
    NEUROMESH_DATABASE_PASSWORD_FILE=./secrets/postgres_password.local \
    pytest -q tests/infrastructure/test_public_read_role_migration.py

## Progress

2026-11-13. The first version of the migration only created the role when
it was missing and accepted any existing role. Tests written before the
fix showed two faults, and both are fixed in this change. An existing role
with LOGIN or any other power attribute was accepted, and an existing role
that already held a privilege, a membership or a member was accepted. The
migration now refuses both and names what it found.

2026-11-13. A test that holds an uncommitted CREATE ROLE open in one
connection while a second runner migrates showed that the second runner
failed with a duplicate key error. The migration now catches that error,
reads the role the first runner created and checks it as in decision 4.

2026-11-13. A test pins what the role can reach in a migrated schema
through PUBLIC. It finds nothing, and it finds a new function when one
is created, so the check is able to fail.
