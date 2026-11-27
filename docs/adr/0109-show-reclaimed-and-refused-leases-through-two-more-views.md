# ADR 0109: Show Reclaimed and Refused Leases Through Two More Views

## Status

Proposed. This ADR decides how the records of ADR 0107 and ADR 0108
reach the public demo. Nothing in it is built yet and nothing is
deployed. Each slice that is built adds a dated entry under Progress.
It amends ADR 0098, decision 1, and ADR 0099, decision 6, on purpose.
Related: ADR 0094, ADR 0097, ADR 0098, ADR 0099, ADR 0102, ADR 0106,
ADR 0107, ADR 0108.

## Context

ADR 0106, items 2 and 3, say the demo page shows the lease that reclaim
removed and the renew or release that was refused. ADR 0107 keeps the
first in lease_reclaims and ADR 0108 keeps the second in
lease_refusals. The public read role has no privilege on either table,
and both ADRs say that a view of these rows needs an ADR of its own
that amends ADR 0098, decision 1.

ADR 0098, decision 1, allows five views and no other. ADR 0099,
decision 6, gives the login role SELECT on the five public views, and
decision 7 says a test compares its privileges with those of the group
role. The public app reads through a port with one method for each view
(ADR 0102), so a new view also needs a record, a method, a route and a
response model. ADR 0094, decision 3, says a field is public only when
it is written in the public package on purpose.

A grant on the two tables is not an option. A grant on a table shows
every column of it, including columns added later, which is the reason
ADR 0098 gives for views.

## Decision

1. Migration 0010 creates two views, public_lease_reclaims and
   public_lease_refusals. No other table gets a view.
   - public_lease_reclaims: id, lease_id, worker_id, job_id,
     lease_acquired_at, lease_expires_at, reclaimed_at, recovered_by.
   - public_lease_refusals: id, lease_id, worker_id, job_id, operation,
     reason, refused_at.
2. Each view names its columns, is created with security_barrier on,
   runs with the rights of its owner and joins public_demo_scope on
   tenant_id, as the five views of migration 0007 do. Neither view has
   tenant_id. ADR 0098, decisions 2 to 6, apply to both unchanged.
3. The migration grants nothing. Migration 0007 is not edited. The
   checksum of 0010 goes into the frozen list in the pull request that
   merges it.
4. ADR 0098, decision 1, now reads seven views, and ADR 0099, decision
   6, now reads seven views. Decision 7 of ADR 0099 stands. The test
   that compares the two roles runs with all seven.
5. scripts/grant_public_read.sql and scripts/create_public_app_role.sql
   name the seven views and ask for migrations up to 0010. The role
   still holds no privilege on lease_reclaims, on lease_refusals or on
   any other base table, and a test says so.
6. The read port gains two frozen records with exactly the columns of
   the views, in the same order, and two methods, list_lease_reclaims
   and list_lease_refusals. Each takes a limit. The reader runs one
   fixed query for each, with named columns, newest first and then id
   ascending, and cuts the limit to its maximum as it does for the
   other views (ADR 0102).
7. The public app gains two GET routes, /public/lease-reclaims and
   /public/lease-refusals. They sit behind the same gate, row limit and
   fixed 503 body as the other routes. Each has a response model of its
   own in the public package (ADR 0094, decisions 2 and 3).

## Consequences

- The page can show the lease that reclaim removed, with its id,
  worker, job, both times and the path that removed it, and each
  refused call, with its operation and reason.
- A refusal is kept only for a lease that reclaim removed (ADR 0108,
  decision 2), and for each lease at most four kinds are kept, two
  operations and two reasons. The refusals view therefore holds at most
  four rows for each row of the reclaims view.
- The body of the 409 is in neither view. The scenario driver records
  it (ADR 0108, decision 6).
- The public database role still cannot read a base table.
- A new view is a migration, a change to the scripts, a change to the
  port, the reader and the routes, and a review.

## Alternatives Considered

- **A grant on the two tables.** Rejected. It shows every column,
  including columns added later (ADR 0098).
- **Rows of the two kinds in public_events.** Rejected. An event has no
  column for a lease id, which ADR 0107 explains, and ADR 0098,
  decision 3, keeps payload out of every view.
- **One view that joins a reclaim with its refusals.** Rejected. A
  reclaim with no refusal would not appear in it, and the page shows
  reclaims on their own.
- **The body of the 409 from the database.** Rejected. Nothing in the
  database holds it (ADR 0108, decision 6).

Not claimed: safe to expose.

## Progress

2026-11-27. The two views and the changes to the scripts are built. The
port, the reader, the routes and the response models are not part of this
slice.

What is built. Migration 0010 creates public_lease_reclaims (id, lease_id,
worker_id, job_id, lease_acquired_at, lease_expires_at, reclaimed_at,
recovered_by) and public_lease_refusals (id, lease_id, worker_id, job_id,
operation, reason, refused_at). Each view names its columns, is created with
security_barrier on, runs with the rights of its owner, joins
public_demo_scope on tenant_id and has no tenant column. The migration
grants nothing, and migration 0007 is unchanged.
scripts/grant_public_read.sql and scripts/create_public_app_role.sql name
seven views and ask for migrations up to 0010. The checksum of 0010 is in
the frozen list.

How it is tested. 25 new tests in
test_public_lease_record_views_migration.py check the seven views that
exist, the columns of each new view, that no private column is shown,
security_barrier and no security_invoker, that the migration grants nothing
on a view or a table, that an empty scope shows nothing, that only the
scoped tenant shows, that each view row equals the row of its base table,
that the role cannot read lease_reclaims or lease_refusals even with the
views granted (each denial is paired with a grant that makes the same read
succeed), and that the role cannot write through either view. The grant
script tests of the views migration test now run on a schema migrated to
0010 and compare with seven views, and one new test shows that at version 7
the script refuses and names the two missing views. The tests of the role
script run at 0010 and compare with seven views, and one new test shows the
same refusal for that script.

What each deliberate break turned red, in the real tests. Each number is the
count of tests that failed.

Migration 0010, 12 breaks. The scope join removed from the reclaims view (2
tests) and from the refusals view (2). security_barrier dropped from the
reclaims view (1) and from the refusals view (1). tenant_id shown by the
reclaims view (2) and by the refusals view (2). The two times swapped in the
reclaims view (1). Operation and reason swapped in the refusals view (1).
lease_id read from the id column in the reclaims view (1). job_id read from
the id column in the refusals view (1). A grant to the role inside the
migration (1). security_invoker set on the reclaims view (4).

Scripts, 6 breaks. The refusals view left out of the grant script (2 tests)
and out of the role script (2). The hint that says 0010 changed to 0007 in
the grant script (1) and in the role script (1). The hint that says seven
views changed to five in the grant script (1) and in the role script (1).

No break survived.

Two flaws in the tests were found and fixed. The hints of the two scripts
were not compared with any text, so reverting them would have passed. Each
is now compared with its exact text. One test still said five views in its
name while it checked seven, and it was renamed.

Not claimed: safe to expose.
