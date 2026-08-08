# ADR 0010: Close PostgreSQL Repository Parity Gap for Lease, Worker, and Job

## Status

Accepted

## Context

AetherGrid's repository abstraction (`NodeRepository`, `JobRepository`, `WorkerRepository`, `LeaseRepository`, `EventRepository`) is meant to let any aggregate be persisted to any backend without the domain or application layers knowing the difference. In practice, PostgreSQL implementations existed only for `Node` and `Event`. `Lease` and `Worker` had in-memory implementations only, and `Job` had in-memory and SQLite but no PostgreSQL implementation, leaving the persistence layer without real parity or contract-test coverage for three of five aggregates.

Building the missing `PostgresLeaseRepository`, `PostgresWorkerRepository`, and `PostgresJobRepository` against real foreign-key-constrained tables surfaced three defects that had been latent in the codebase:

1. `NodeId` had no validating constructor. Unlike `WorkerId` and `JobId`, it accepted any string, including non-UUID values, without raising. Several test files (`test_worker_agent.py`, `test_create_worker_service.py`, and the original `WorkerRepositoryContract`) relied on this gap to construct `NodeId("node-1")`, silently producing domain objects whose identifiers were never real value objects.
2. `WorkerRepositoryContract` was structurally inconsistent with `LeaseRepositoryContract` and `NodeRepositoryContract` (an `ABC` with abstract methods rather than a `pytest.fixture`-based class), and its test bodies constructed `Worker` and `Node` using raw strings instead of real identifiers. It passed, but it was not exercising the actual `WorkerRepository` contract.
3. `JobStatus.SUBMITTED` was defined as `"SUB,ITTED"`, a typo that had never surfaced because every round trip through the enum went through `.value` on save and reconstruction on load, both symmetric and both using the same incorrect constant.

Writing PostgreSQL implementations against schema-enforced foreign keys also made an implicit invariant explicit: `Worker.save()` requires its `Node` to already exist, and `Lease.save()` requires its `Worker` and `Job` to already exist. Tracing the real call paths (`workers` router → `GetNodeService` → `CreateWorkerService`; `AssignWorkerService` → `AcquireLeaseService`) confirmed this is exactly how the system already behaves in production: the API layer fetches or creates the referenced node/job/worker before the dependent aggregate is ever persisted. The database constraints therefore encode an invariant the application layer already upholds, rather than introducing a new one.

## Decision

- Add `workers` and `leases` tables to `schema.sql`, with `leases.worker_id` and `leases.job_id` as `UNIQUE` foreign keys (enforcing the domain rule that a job and a worker each hold at most one active lease at a time) and `ON DELETE CASCADE`/`SET NULL` chosen per the same reasoning already used for `jobs.assigned_node_id`.
- Implement `PostgresWorkerRepository`, `PostgresLeaseRepository`, and `PostgresJobRepository` using the same conventions already established by `PostgresNodeRepository` and `PostgresEventRepository`: raw `psycopg`, explicit `%(named)s` parameters, `ON CONFLICT (id) DO UPDATE`, and a `_to_entity` reconstruction method.
- Fix `NodeId` to validate through `UUID(str(value))` in `__init__`, matching `WorkerId`, and update the five call sites that depended on the previous unvalidated behavior to use `.new()` instead.
- Rewrite `WorkerRepositoryContract` to match the `pytest.fixture`-based pattern used by `LeaseRepositoryContract`/`NodeRepositoryContract`, using real `WorkerId.new()`/`NodeId.new()` construction, and comparing reconstructed entities by identity value rather than Python object identity, since a real repository returns a new object on read, not the same instance that was saved.
- Fix `JobStatus.SUBMITTED` to `"SUBMITTED"`.
- Do not have `PostgresWorkerRepository.save()` or `PostgresLeaseRepository.save()` silently upsert their referenced dependencies. The foreign key constraints are intentional; callers are expected to persist referenced aggregates first, matching production behavior.

## Consequences

All five repository types (`Node`, `Job`, `Worker`, `Lease`, `Event`) now have PostgreSQL implementations. `Node`, `Job`, and `Event` have full in-memory/SQLite/PostgreSQL parity with shared contract tests; `Worker` and `Lease` have in-memory/PostgreSQL parity (no SQLite implementation exists for these two, which is an accurate reflection of current scope, not an oversight to hide).

Foreign key constraints on `workers` and `leases` now enforce, at the database level, invariants that were previously only implicit in call order (a worker's node must exist; a lease's worker and job must exist). Any future code path that violates this order fails immediately and loudly with a `ForeignKeyViolation`, rather than silently succeeding the way the in-memory repositories would.

The three defects found above were caught specifically because contract tests were written against real constrained storage rather than an in-memory dictionary. This is the practical argument for contract testing across backends: an abstraction that only compiles against a permissive backend can hide invariant violations indefinitely.
