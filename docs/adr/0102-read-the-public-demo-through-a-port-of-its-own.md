# ADR 0102: Read the Public Demo Through a Port of Its Own

## Status

Proposed.

Related: ADR 0064, ADR 0082, ADR 0094, ADR 0097, ADR 0098 and ADR 0099.

## Context

ADR 0094, decision 7, says the public app reads through the existing
application services and repository interfaces. That cannot be built:

- The repositories select from base tables and scope by a tenant
  argument. The public role has no privilege on any base table (ADR
  0097), and the five public views carry no tenant column (ADR 0098).
- The layer rules (ADR 0082) let presentation import infrastructure only
  in the composition root, allow psycopg_pool only there and in
  infrastructure, and allow one entry point that imports only
  app.presentation.api. They have no place for a second app.
- resolve_database_password reads the NEUROMESH_ names, and the public
  settings forbid any fallback to them (ADR 0094).
- PublicSettings still requires AETHERGRID_PUBLIC_TENANT_ID, but ADR 0098,
  decision 6, moved the tenant into public_demo_scope. The app cannot read
  that table, so the setting and the database can disagree and nothing
  would notice.

## Decision

1. One port, app/application/public_read_port.py: a read-only protocol
   with one method per public view (nodes, jobs, workers, leases, events)
   and one frozen record type per view with exactly the view's columns.
   No method takes a tenant. Every method takes a limit, and the reader
   clamps it to a fixed maximum. Every read has a fixed order, and events
   come newest first.
2. A Postgres reader in app/infrastructure/public_read/ implements the
   port. It selects from the five public_* views and from nothing else. A
   test fails if any query in the package names another relation.
3. A function in the same package opens the pool from plain values, a URL
   and a password file path, so infrastructure never imports presentation
   settings. The pool has min_size 1, max_size 5, timeout 2.0 seconds,
   autocommit, and connection options statement_timeout 2000 ms and
   default_transaction_read_only on. The role cannot write anyway, so the
   options are a second barrier and bound a slow query. The timeout is
   the 2 seconds of /health (ADR 0046), not the 5 seconds of the private
   pool (ADR 0051), because an anonymous caller should not hold a thread
   longer than a probe does.
4. The password is read by a shared helper, read_password_file(path,
   setting), extracted from database_credentials.py. resolve_database_password
   calls it and its messages do not change. The public side passes its own
   setting name, so a public error never names a NEUROMESH_ variable.
5. Routes depend on the port. No application service is added until a rule
   needs one, because a pass-through would remove no complexity. The
   public import allowlist gets this one module and nothing else.
6. app/public_main.py is a second entry point that imports only
   app.presentation.public.composition. That module is a second
   composition root: it reads the environment, opens the pool, builds the
   reader and hands it to create_public_app. It may import infrastructure
   and may not import psycopg_pool. The layer test turns its single
   ENTRY_POINT and COMPOSITION_ROOT into tables, and PORTS_IMPLEMENTED
   gains the port module. Each new row comes with a case that must be
   refused.
7. When the reader fails, a route returns 503 with a fixed body. The
   response never carries an exception class or message.
8. AETHERGRID_PUBLIC_TENANT_ID is removed. The tenant lives only in
   public_demo_scope, set by scripts/set_public_demo_tenant.sql. This
   records that ADR 0098, decision 6, replaced ADR 0094, decision 5, and
   that this ADR replaces decision 7.
9. Public responses name allocation, not use. The views hold capacity and
   available, so a bar shows the allocated share, capacity minus
   available. No field or label says usage or utilization.

## Consequences

- The domain gains nothing, as ADR 0094 requires, and the private app and
  its ADR 0064 tests are untouched.
- The layer test is looser in two named places, a second entry point and a
  second composition root, and tighter in one: the public root may not
  import psycopg_pool.
- The public settings tests change on purpose, because of decision 8.
- A new public field is a view migration, a record field, a schema field
  and a test.
- The public app has no rate limiter yet, so nothing is deployed (ADR
  0094).

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That the pool values are right. They are first values, to be measured.

## Alternatives Considered

- **Repositories with a tenant argument and grants on base tables.**
  Rejected. ADR 0098 rejected base table grants.
- **The port in domain/repositories.** Rejected. A read model of views is
  not an aggregate repository, and ADR 0094 says the domain gains nothing.
- **A new application subpackage.** Rejected. scheduler_leadership is the
  precedent: one module, named in PORTS_IMPLEMENTED.
- **Presentation queries the views with psycopg.** Rejected. The layer
  rules refuse it, and a route could not be tested without a database.
- **Reuse the private pool and credential reader.** Rejected. It reads the
  NEUROMESH_ names, which ADR 0094 forbids falling back to, and a shared
  pool would put the public app on the private connections.
- **Keep the tenant setting and compare it with the database.** Rejected.
  The app cannot read public_demo_scope, so only an operator script could
  compare them, and a value that nothing consumes can only mislead.

## Progress

2026-11-17. Decision 4 is built: read_password_file in
database_credentials.py (PR 526), with the private messages pinned before
the refactor.

2026-11-17. Decision 8 is built: the tenant setting is gone from the public
settings, and a stale value of the old variable, valid, malformed or empty,
changes nothing. Putting the field back, or requiring the variable again,
failed the new tests. Decisions 1 to 3, 5 to 7 and 9 are not built.

## How to Verify

    pytest -q tests/architecture tests/presentation/public
