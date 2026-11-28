# ADR 0106: Fence Job Cancellation Writes by the Lifecycle State Read

## Status

Accepted.

Related: ADR 0029, ADR 0064 and ADR 0092.

## Context

`CancelJobService.execute` reads a job with `get_by_id`, transitions it
in memory (`request_cancellation` when `RUNNING`, `cancel` when `QUEUED`
or `SCHEDULED`, and nothing when already `CANCELLING`), and then calls
`JobRepository.save` unconditionally.

Three races violate the invariants of ADR 0029 and retry accounting:

1. **A running or cancelling job finishes before the cancel write.** ADR
   0029 states that when a subprocess finishes on its own before the
   cancellation reaches it, whichever happens first wins and the real
   outcome is recorded. With an unconditional `save`, a cancel request
   that read `RUNNING` (or `CANCELLING`) before the worker saved
   `COMPLETED` or `FAILED` writes `CANCELLING` over the settled outcome,
   leaving the finished job stranded in `CANCELLING` with no live lease.
2. **A scheduled job starts before the cancel write.** ADR 0029 warns
   that forcing an immediate `CANCELLED` onto a running job is worse
   than the gap ADR 0029 closes, because it marks the job cancelled
   while its subprocess is still alive. If a scheduler or worker
   transitions a job from `SCHEDULED` to `RUNNING` after
   `CancelJobService` read `SCHEDULED`, the unconditional `save` writes
   `CANCELLED` over `RUNNING` without ever requesting termination
   through lease renewal.
3. **A running job fails, retries, and re-enters `RUNNING` on another
   attempt before the cancel write (ABA race).** Fencing on `status`
   alone would match `RUNNING` on the new attempt while writing back the
   stale `Job` snapshot's `retry_count`, `assigned_node_id`, and
   `started_at`, silently corrupting the new execution attempt's
   metadata.

## Decision

1. `JobRepository` gains `save_if_unchanged(job, expected) -> bool`. It
   persists `job` only when the stored row in `job.tenant_id` still
   matches every mutable lifecycle field of `expected` (`status`,
   `retry_count`, `assigned_node_id`, `started_at`, `completed_at`,
   `exit_code`, and `cancellation_requested_at`), returning `True` when
   the row matched and was updated and `False` when the job is missing
   in `job.tenant_id` or any lifecycle field changed since `expected`
   was read. It raises `ValueError` when `expected` does not share `id`
   and `tenant_id` with `job`, and raises `JobTenantConflictError` when
   `job.id` belongs to another tenant (ADR 0064).
2. `PostgresJobRepository.save_if_unchanged` runs one CTE statement
   whose conditional `UPDATE jobs ... WHERE id = %(id)s AND tenant_id =
   %(tenant_id)s AND status = ... AND retry_count = ... AND
   assigned_node_id IS NOT DISTINCT FROM ... RETURNING 1` performs the
   compare-and-swap atomically under PostgreSQL's `FOR NO KEY UPDATE`
   row lock (including `EvalPlanQual` re-evaluation after waiting on a
   concurrent writer), while the outer `SELECT` checks `tenant_id` to
   distinguish a missing or changed row from a cross-tenant conflict
   without locking rows in other tenants or blocking `FOR KEY SHARE`
   foreign-key checks on `leases`, `events` and `workers`.
3. `SqliteJobRepository.save_if_unchanged` executes the equivalent
   conditional `UPDATE` using `IS ?` for nullable columns and commits
   after the statement even when zero rows match, releasing SQLite's
   implicit `RESERVED` write lock without calling `rollback()` on a
   connection shared with sibling SQLite repositories.
   `InMemoryJobRepository` guards all reads and writes with a re-entrant
   lock (`threading.RLock`), verifies `_lifecycle_matches(existing,
   expected)`, and copies slots onto the stored instance only when the
   snapshot matches.
4. `CancelJobService.execute` deep-copies the read `Job` into `expected`
   immediately. When `expected` is already `CANCELLING`, it returns
   without writing. Otherwise it transitions a separate copy
   (`candidate`) so a refused write never mutates a shared in-memory
   instance, and persists via `save_if_unchanged(candidate, expected)`.
   When `save_if_unchanged` returns `False`, the service re-reads the
   job and decides against the fresh state, up to 8 attempts. If 8
   concurrent state changes prevent convergence, it raises
   `JobStatusConflictError`, which the jobs router maps to HTTP 409
   alongside `InvalidJobTransition`.

## Consequences

- A cancel request that loses a race to `COMPLETED`, `FAILED`, or
  `CANCELLED` refuses to overwrite the settled outcome, re-reads it, and
  raises `InvalidJobTransition` (HTTP 409) unless another actor has
  meanwhile retried a `FAILED` job back into `QUEUED`, in which case the
  re-read cancels that newly queued attempt cleanly.
- A cancel request that read `SCHEDULED` while a worker started the job
  refuses to overwrite `RUNNING` with `CANCELLED`, re-reads `RUNNING`,
  and transitions the job to `CANCELLING` as ADR 0029 requires.
- A cancel request whose `RUNNING` snapshot loses an ABA race across
  `FAILED -> retry() -> RUNNING` refuses to clobber the new attempt's
  `retry_count`, `assigned_node_id`, and `started_at`, re-reads the new
  attempt, and requests cancellation on it cleanly.
- Calling `CancelJobService` on a job already in `CANCELLING` is a pure
  read and cannot overwrite a concurrent terminal write.

## Not Claimed

- That other callers of `JobRepository.save` (such as outcome reporting
  or reconciliation) fence their writes yet. Only `CancelJobService`
  uses `save_if_unchanged` in this change.
- That `InMemoryJobRepository` isolates callers that mutate a returned
  `Job` reference directly in place outside repository methods after
  `expected` was captured. `InMemoryJobRepository.get_by_id` returns the
  stored instance to match existing worker loops; `CancelJobService`
  snapshots `expected` with `copy.deepcopy` before applying transitions,
  while multi-statement row isolation belongs to PostgreSQL and SQLite.

## Alternatives Considered

- **Fence only `status` (`save_if_status`).** Rejected. A job with
  retries remaining can move from `RUNNING` through `FAILED -> QUEUED ->
  SCHEDULED -> RUNNING` between read and write; matching `status` alone
  would let the stale write overwrite the new attempt's `retry_count`,
  `assigned_node_id`, and `started_at`.
- **Select the row `FOR UPDATE` in a preliminary CTE before `UPDATE`.**
  Rejected. `FOR UPDATE` blocks `FOR KEY SHARE` foreign-key checks from
  concurrent inserts into `leases`, `events` and `workers`, locks rows
  belonging to other tenants before the tenant predicate runs, and
  dirties pages when predicates do not match, whereas a conditional
  `UPDATE` acquires `FOR NO KEY UPDATE` only on matching rows and still
  re-evaluates `WHERE` via `EvalPlanQual` under `READ COMMITTED`.
- **Call `rollback()` in `SqliteJobRepository` when zero rows match.**
  Rejected. Production SQLite repositories share a single
  `sqlite3.Connection`; rolling back a zero-row `UPDATE` would discard
  uncommitted statements from sibling repositories on the same
  connection, whereas committing the zero-row no-op releases the
  `RESERVED` lock without losing sibling work.

## How to Verify

```bash
pytest -q tests/architecture tests/application/test_cancel_job_service.py tests/presentation/test_cancel_job_api.py tests/infrastructure/repositories/test_in_memory_job_repository_save_if_unchanged.py tests/infrastructure/repositories/test_sqlite_job_repository_save_if_unchanged.py tests/infrastructure/repositories/test_postgres_job_repository_save_if_unchanged.py
```
