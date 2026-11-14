# ADR 0099: Give the Public App a Login Role of Its Own

## Status

Proposed.

Related: ADR 0094, ADR 0097 and ADR 0098.

## Context

The public app has its own database settings, a URL and a password file,
and no fallback to the private ones (ADR 0094). It needs a role to log in
as. aethergrid_public_read cannot be that role. It is a NOLOGIN group role,
and ADR 0097 refuses to run against a database where it has a member or a
privilege that is not the five views.

A migration cannot carry a password, and a login role created by a
migration would exist in every database that migrates, not only in the one
that serves the public.

## Decision

1. The login role is aethergrid_public_app. It is not a member of
   aethergrid_public_read and has no member. ADR 0097 stays as written.
2. A script, scripts/create_public_app_role.sql, creates it on the demo
   database. An operator runs it. It is not a migration and must never be
   placed in the migrations folder.
3. The password comes from the file that AETHERGRID_PUBLIC_APP_PASSWORD_FILE
   names. The script reads it with psql and never takes it from the command
   line, so it does not appear in a process list or in shell history. The
   script never prints it. psql reads the file through a backtick command, so
   the script depends on a shell and trusts the file's path. The shell reads
   the path from the environment, so it is never part of the SQL text. The
   script refuses an empty file, because an empty password in ALTER ROLE
   removes the password.
4. The role has none of the power attributes: NOSUPERUSER, NOCREATEDB,
   NOCREATEROLE, NOREPLICATION and NOBYPASSRLS.
5. The role has a connection limit and a statement timeout, both set on the
   role itself, so a leaked password cannot exhaust the server or run a
   query for an unbounded time.
6. The role holds USAGE on the schema and SELECT on the five public views,
   and nothing else. It cannot create an object anywhere, and it cannot
   read any base table, including tenants, api_keys and public_demo_scope.
7. aethergrid_public_app and aethergrid_public_read hold the same
   privileges. A test compares them, so one cannot gain a privilege that
   the other lacks without the build failing.
8. The script stops without changing anything if the role exists with a
   power attribute, with a privilege on any other relation, or with a
   member. Running it again for a clean role updates the password and the
   limits and changes nothing else.

## Consequences

- Two roles carry the same grants. The grant script applies to both, and
  the comparison test is what keeps them equal.
- A leaked password gives read access to the five views of one tenant, at
  a bounded connection count and query time, and nothing else.
- The public app has two sources for its tenant: AETHERGRID_PUBLIC_TENANT_ID
  and public_demo_scope. Neither can be changed by a request. They can
  disagree, so the next change makes the app refuse to start when they do.
- The password file is trusted by its path. The operator controls it.
- ALTER ROLE sends the password to the server as text. A server with
  log_statement turned on can write it to its log. The script cannot
  prevent that, so the operator keeps log_statement at none.
- The script runs a shell command to read that file. An operator who can
  change the path or the file can change the password the role gets, and
  that operator can already run the script as the owner of the database.

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That the public app uses this role. It still has no database access.

## Alternatives Considered

- **A login role that is a member of aethergrid_public_read.** Rejected. It
  needs ADR 0097 to accept one known member, which turns a check that has
  no exceptions into one with an allowlist.
- **Make aethergrid_public_read itself a login role.** Rejected. ADR 0097
  chose a role that cannot log in, so that no credential exists for it.
- **Create the role in a migration.** Rejected. A migration cannot carry a
  password, and it would create a login identity in every database that
  migrates.
- **Pass the password on the command line.** Rejected. A command line shows
  in a process list and in shell history.

## Progress

2026-11-14. The first version of the script left the role with no
password. psql does not expand a variable inside a backtick command, so cat
received a literal name, the file read as empty, and ALTER ROLE with an
empty password removes the password. A test that reads the stored hash
failed, and the other tests passed. The script now reads the path from the
environment and refuses an empty file.

2026-11-14. The first fix printed the password. The statement that carries
it into a setting returns it as a result, and psql prints results. A test
that searches the output for the password failed. The statement now runs
with its output sent nowhere.

2026-11-14. Each refusal in the script was disabled by hand and a test failed
every time except for the one about members, which had no test. Two tests
were added, and the refusal was disabled again.

## How to Verify

    NEUROMESH_TEST_DATABASE_URL=postgresql://neuromesh@127.0.0.1:5433/neuromesh_test \
    NEUROMESH_DATABASE_PASSWORD_FILE=./secrets/postgres_password.local \
    pytest -q tests/infrastructure/test_public_app_role_script.py
