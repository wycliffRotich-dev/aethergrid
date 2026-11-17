# ADR 0104: Fence Lease Release Deletion by Lease Identity at Delete Time

## Status

Proposed.

Related: ADR 0034, ADR 0036, ADR 0038 and ADR 0052.

## Context

ReleaseLeaseService fenced its read by lease identity (ADR 0034): it
read the worker's current lease, compared its id to the id the caller
believes it holds, and refused to release when they differed. The delete
itself, though, was still by job id alone. LeaseRepository.delete(job_id,
tenant_id) removes whatever lease holds that job.

Between the read and the delete, reconciliation can reclaim a lease that
has just expired and hand the same job to a different worker with a new
lease. The stale caller's release then deletes that new, legitimately-held
lease. The id check at read time cannot stop it, because at read time the
lease was still current; the swap happens after.

The same class of race was closed for renewal (ADR 0038), for the
standalone agent's outcome report (ADR 0036), and for reconciliation's own
delete, which re-checks expiry at delete time (ADR 0052). The release
delete was the remaining lease-mutating operation whose delete was not
conditional on the identity checked before it.

## Decision

1. LeaseRepository gains delete_if_matches(job_id, tenant_id,
   expected_lease_id). It deletes the lease for job_id in tenant_id only
   when its id is still expected_lease_id, in one atomic statement, and
   returns True when a row was deleted and False otherwise.
2. A lease in another tenant, or no lease at all, returns False and leaves
   the row untouched, matching every other scoped method.
3. ReleaseLeaseService calls delete_if_matches with the same expected
   lease id it verified at read time. A False result means the lease is
   no longer the lease verified at read time, so the service raises
   LeaseNotFoundError and records nothing.
4. Both the in-memory and the Postgres backends implement the method, and
   the shared contract tests it on each.

## Consequences

- A stale release can no longer delete a lease that a different caller
  now holds for the same job.
- On Postgres the id check and the delete are one SQL statement, so a
  concurrent writer cannot separate them.
- Adding an abstract method means a new backend cannot start without
  implementing it.

## Not Claimed

- That the fence is needed on the other delete() caller. reclaim_job in
  app/application/services/job_execution_support.py still deletes by job
  id, but that is the system reclaiming its own lease, not a stale
  caller releasing, and the recovery services precede it with
  delete_if_expired.
- That the race was observed live. The window is narrow, and it is shown
  by a test that forces the order, not by two writers running at once.

## Alternatives Considered

- **Keep delete() and re-check the id in the service just before it.**
  Rejected. A second read still leaves the read-then-delete gap that a
  conditional delete removes.
- **Delete by lease id instead of job id.** Rejected on its own.
  delete_if_matches keeps job_id in the predicate, consistent with
  delete_if_expired, and adds the id as the fence.

## How to Verify

```bash
pytest -q tests/infrastructure/repositories/test_in_memory_lease_repository_contract.py tests/infrastructure/repositories/test_postgres_lease_repository_contract.py tests/application/test_release_lease_service.py tests/application/test_release_lease_service_against_postgres.py
```

All of them pass. The Postgres contract test is the only proof of the
DELETE predicate. Before the change the service test fails because the
service deletes by job id and raises nothing.

## Progress

2026-11-16. The six contract tests for delete_if_matches and the service
test that stages the reclaim-and-re-lease race were written to specify
the fence. The service test fails before the change: execute() deletes by
job id and raises nothing, so the pytest.raises(LeaseNotFoundError)
assertion fails. After the change the in-memory contract, release-service
and ADR-numbering tests pass (39 tests), and the Postgres contract and
release-service tests pass (22 tests) against a real database with
migrations applied. ruff and mypy are clean.
