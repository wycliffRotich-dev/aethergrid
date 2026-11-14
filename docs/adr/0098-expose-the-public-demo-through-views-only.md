# ADR 0098: Expose the Public Demo Through Views Only

## Status

Proposed.

Related: ADR 0071, ADR 0094 and ADR 0097.

## Context

ADR 0094 says a field is public only when it is written there on purpose,
and that the public app reads one tenant chosen by server configuration.
ADR 0097 created the role aethergrid_public_read with no privilege. The
role now needs something to read.

A grant on a base table lets the role read every column of it, including
columns added later, and every tenant. The tables hold a job command, free
form event payloads, node labels and API key hashes.

## Decision

1. Migration 0007 creates five views: public_nodes, public_jobs,
   public_workers, public_leases and public_events. No other table has a
   view. Nothing is created for tenants or api_keys.
2. Each view names its columns. A column added to a table later is not
   public until a migration adds it to the view.
   - public_nodes: id, name, capacity_cpu_cores, capacity_memory_mib,
     capacity_vram_mib, available_cpu_cores, available_memory_mib,
     available_vram_mib, last_seen_at, draining.
   - public_jobs: id, cpu_cores, memory_mib, vram_mib, priority,
     max_retries, retry_count, status, assigned_node_id, submitted_at,
     started_at, completed_at, execution_timeout_seconds.
   - public_workers: id, node_id, status, running_job_id, last_seen_at.
   - public_leases: id, worker_id, job_id, acquired_at, expires_at.
   - public_events: id, aggregate_id, aggregate_type, event_type,
     occurred_at.
3. No view exposes tenant_id, command, constraints, labels, exit_code,
   cancellation_requested_at, managed_by or payload.
4. The views run with the rights of their owner, not of the caller. The role
   needs no privilege on any base table. They are not security_invoker.
5. Each view is created WITH (security_barrier = true), so a function that
   a caller puts in a query cannot see a row before the tenant filter has
   removed it.
6. The tenant is stored in a table, public_demo_scope, that holds at most
   one row. Every view joins it on tenant_id. Only the migration owner and
   the operator can read or write it, and the role has no privilege on it.
   A request cannot choose the tenant, which meets ADR 0094, decision 5.
   An empty table shows no rows.
7. Migration 0007 grants the role nothing. The grants are in a script,
   scripts/grant_public_read.sql, that an operator runs on the demo
   database. It gives the role USAGE on the schema and SELECT on the five
   views, and nothing else.

## Consequences

- Every database that runs the migrations has the views and the empty scope
  table, and only the demo database has the grants.
- ADR 0097 refuses to run against a database where the role already holds
  a privilege. The demo database therefore keeps one schema, as every
  database does today, and the tests that migrate scratch schemas never
  receive the grants.
- The filter in the views costs a join and limits the planner because of
  decision 5. The demo reads small tables.
- A new public field is a migration, a test and a review.
- The grant script is tested by running it in a scratch schema and checking
  that the role can read each view and nothing else.

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That the public app reads these views. It still has no database access
  (ADR 0094).

## Alternatives Considered

- **SELECT on the base tables with row level security.** Rejected. The
  policy would be the only barrier between the public and every other
  tenant, and api_keys would sit one wrong grant away in the same schema.
- **Filter by tenant in the public app.** Rejected. A mistake in one query
  would expose every tenant, and the database would not refuse it.
- **Keep the tenant in a session setting.** Rejected. A session can change
  a custom setting, so a compromised connection could pick another tenant.
- **Grant in the migration.** Rejected. It would put a grant in every
  database that migrates, and ADR 0097 would then refuse the next schema
  of that database.
- **Views with security_invoker.** Rejected. The role would then need
  SELECT on the base tables, which is what this change avoids.

## How to Verify

    NEUROMESH_TEST_DATABASE_URL=postgresql://neuromesh@127.0.0.1:5433/neuromesh_test \
    NEUROMESH_DATABASE_PASSWORD_FILE=./secrets/postgres_password.local \
    pytest -q tests/infrastructure/test_public_read_views_migration.py
