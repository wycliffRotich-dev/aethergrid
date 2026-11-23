# ADR 0106: Build the Demo Page From a Real Run of One Scenario

## Status

Proposed. This ADR is the list of what is built for the demo page, so that
none of it is forgotten. Nothing in it is built yet and nothing is
deployed. Each item that changes the architecture gets its own ADR before
any code. Related: ADR 0094, ADR 0097, ADR 0098, ADR 0102, ADR 0103,
ADR 0104.

## What will be built

The page shows a real run of one fixed scenario on the demo tenant: a
worker takes a lease and stalls past its 30 seconds, reconciliation
reclaims the job, a second worker takes a new lease, and the first
worker's renew and release are refused with 409. Every number and line on
the page comes from a record of that run. A panel with no record behind it
is built before the page shows it.

1. The scenario driver. It runs outside the public app, with its own
   credentials, and the public app stays GET only. It has its own ADR and
   its tests before any code. A run takes about a minute.
2. A record of a refused renew or release. Today nothing records the 409,
   so no view can show it. The record carries the stale lease id, the
   worker and the job. Its shape is decided in its own ADR.
3. A record of the lease that reclaim deletes. The row is gone after
   reclaim, so its id and expiry are kept at that moment.
4. Public views for 2 and 3, and for the job details the page needs, in a
   new migration 0008. Migration 0007 is pinned by checksum and is not
   edited. Each new column goes through the grant script, the read port,
   the response model, the route and the test helper for the views.
5. A database check behind the Database status panel, and a recorded
   series of checks behind the health chart.
6. The execution log panel, read from fixed lines the driver writes for
   the run. It is a record of its own and not the operator log.
7. The tenant panel shows what ADR 0098, decision 3 allows. Its wording is
   decided in its own ADR.
8. The page is a separate frontend entry. It calls only the /public routes
   with no Authorization header and no key, and it does not use client.ts,
   AuthGate or the heartbeat hook. It is built with the allowed origin of
   the deployed demo. The job detail panel is built from the lists or from
   a new route.
9. The page shows when the last run happened. It says "Live Demo" only
   while a run is real.
10. The wording is what the code supports. "A lease lasts 30 seconds and
    its worker renews it every 10." "A job is reclaimed only after its
    lease has expired." "A stale renew or release is refused with 409. The
    lease id is compared in the service and again in the SQL." The
    headline "Don't trust the worker. Verify the lease." stays, and
    "Proven Safe" becomes "Checked at the lease".
11. Deployment (service definitions, proxy and TLS, secrets, the role
    scripts, the migration on the target, the demo tenant) has its own ADR
    and tests.

Not claimed: safe to expose.

## Progress

2026-11-23. Two sentences of item 10 are corrected, because the code does
something other than they say.

A job is reclaimed in three ways. Reconciliation reclaims a job whose
lease has expired. RecoverOfflineNodeService reclaims the job of a worker
on an offline node when the job has no lease or an expired one.
CreateWorkerService reclaims the job of a worker whose node registers
again (ADR 0039). The sentence "A job is reclaimed only after its lease
has expired" is replaced by "Reconciliation reclaims a job whose lease has
expired", which is the case the scenario runs.

A stale lease is refused with 409 by the route that renews a lease and by
the three outcome routes: complete, fail and cancel. There is no release
route. The release runs inside the outcome report, and the loop of a
worker that the server runs calls it directly. The sentence "A stale renew
or release is refused with 409" is replaced by "A stale renew or outcome
report is refused with 409". The lease id is compared in the service and
again in the SQL, for renew and for release.

Not claimed: safe to expose.
