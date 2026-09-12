# ADR 0037: Verify Lease Fencing Against a Real, Reconstructing Repository

## Status

Accepted

## Context

ADR 0034 introduced identity fencing on `ReleaseLeaseService.execute()`,
and ADR 0036 closed the same gap for the standalone-agent's external
HTTP path. Both were verified with tests before any fix landed, and
both tests genuinely proved the bugs they targeted. But every one of
those tests, and every test written since that exercises
`expected_lease_id`/`lease_id` fencing, runs exclusively against
`InMemoryLeaseRepository`.

This codebase has already been burned once by exactly this class of
false confidence. ADR 0033's own Context section documents it
directly: `InMemoryJobRepository.get_by_id()` returns the same
object reference on every call, so a test built on it cannot
exhibit a race between two independent readers at all, "any
'concurrent' mutation in a test built on it is actually mutating
the loop's own in-memory job directly." The first attempt at a
repro test for that bug passed against unpatched code for the wrong
reason, and only a rewrite against `SqliteJobRepository`, using
three genuinely separate connections, proved the bug and then the
fix for real.

`InMemoryLeaseRepository` has the identical shape. Its `save()`
stores the exact `Lease` object instance it's given; `get_by_worker_id()`
and `get_by_job_id()` return that same instance back, not a
reconstruction from serialized state. Every fencing test that
constructs a `Lease`, saves it, then later compares
`expected_lease_id` against what a read call returns, is, in the
in-memory case, potentially comparing an object against itself or
a value derived from itself, not against an independently
reconstructed read the way `PostgresLeaseRepository` and (if a
SQLite implementation exists) `SqliteLeaseRepository` would
produce.

This has not been confirmed to hide an actual bug. ADR 0034 and
0036's fencing logic operates on `lease.id`, a plain UUID value
compared by equality, not on object identity, so the specific
reference-sharing failure mode that broke the first ADR 0033 repro
attempt may not apply here in the same way. That distinction is
exactly the kind of thing that should be verified directly against
a real backend, not assumed safe by analogy. Given this exact
class of false confidence has already cost real debugging time once
in this codebase, and given lease fencing is one of the more
safety-critical mechanisms added this session, closing the gap in
test coverage is worth doing before, not after, a real incident
forces the question.

## Decision

Add a repository-contract-level test (or a targeted application-
service test built directly against `PostgresLeaseRepository`,
following the same three-separate-connection idiom already
established for the SQLite job-repository repro in ADR 0033)
that exercises the full lease-fencing scenario ADR 0034 describes:

1. Acquire a lease for `(Worker W, Job 1)` via one connection/
   repository instance, capturing its `lease.id`.
2. Simulate reconciliation reclaiming it: delete that lease via a
   second, independent connection/repository instance.
3. Simulate a fresh, legitimate reassignment: acquire a new lease
   for `(Worker W, Job 2)` via that same or another independent
   connection/repository instance.
4. Attempt to release the original, now-stale `lease.id` via a
   third independent connection/repository instance, calling
   `ReleaseLeaseService.execute()` exactly as a real caller would.
5. Assert it raises `LeaseNotFoundError`, and that the second,
   legitimately-held lease is untouched, read back via a fourth,
   independent verification connection.

If this test passes cleanly against `PostgresLeaseRepository` on
the first attempt, ADR 0034 and ADR 0036's fencing logic is
confirmed correct against a real backend, not just assumed correct
by extension from the in-memory suite, and this ADR's job is done:
add the test, document that it was verified, no production code
changes needed. If it does not pass cleanly, the real bug it finds
becomes its own, separate, evidence-based fix, following this
session's standing rule: prove the gap first, fix it second.

## Consequences

### Positive

- Closes a real hole in test coverage for two of this session's
  most safety-critical fixes, without assuming the in-memory suite
  generalizes.
- Directly reuses the multi-connection repro idiom already proven
  out in ADR 0033, rather than inventing a new testing pattern.
- Either confirms ADR 0034/0036 are correct against a real backend
  (closing this ADR cleanly), or surfaces a real, previously-hidden
  bug (opening a new, properly scoped fix).

### Negative

- Requires a live Postgres connection to run, consistent with this
  codebase's existing contract-test suite, not a new category of
  test infrastructure.
- If the fencing logic does prove correct on the first attempt,
  this ADR's positive outcome is essentially a confirmation, not a
  fix, some effort spent for a negative result. Judged worthwhile
  given the specific, already-realized cost of the equivalent gap
  in ADR 0033's own history.

## Alternatives Considered

### Trust the in-memory test suite by analogy, since fencing compares plain UUID values rather than object identity

Rejected as the ADR's own starting decision, not adopted.

This is exactly the reasoning that made the first ADR 0033 repro
attempt pass for the wrong reason: assuming a lower-fidelity test
double generalizes to real backend behavior without checking. The
distinction between comparing object identity and comparing a UUID
value by equality is a real, plausible reason the two cases might
differ in outcome, not a reason to skip verification.

### Rewrite every existing in-memory fencing test to use PostgresLeaseRepository instead of adding new tests

Rejected.

The existing in-memory tests are fast, deterministic, and correctly
verify the fencing *logic* in isolation; they do not need to be
thrown away. What's missing is a smaller, targeted set of tests
proving that logic holds against a repository with real
reconstruct-on-read semantics, additive coverage, not a wholesale
replacement of what already works.
