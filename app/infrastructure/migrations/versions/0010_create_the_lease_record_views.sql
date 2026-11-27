-- ADR 0109: two more public views, for the records of ADR 0107 and 0108.
-- public_lease_reclaims shows the leases that reclaim removed, and
-- public_lease_refusals shows the renews and releases that were refused.
--
-- Each view names its columns, runs with the rights of its owner, is
-- security_barrier and joins public_demo_scope on tenant_id, as the five
-- views of migration 0007 do. Neither view has tenant_id. It grants nothing
-- to anyone: scripts/grant_public_read.sql does that on the demo database,
-- because ADR 0097 refuses to migrate a database where the role already
-- holds a privilege. The public role has no privilege on lease_reclaims or
-- lease_refusals, so a column added to either table later is not public
-- until a new migration adds it to its view.
--
-- This migration only adds views, so an older image keeps working after a
-- rollback (ADR 0071, decision 7).

CREATE OR REPLACE VIEW public_lease_reclaims WITH (security_barrier = true) AS
SELECT
    r.id,
    r.lease_id,
    r.worker_id,
    r.job_id,
    r.lease_acquired_at,
    r.lease_expires_at,
    r.reclaimed_at,
    r.recovered_by
FROM lease_reclaims r
JOIN public_demo_scope s ON s.tenant_id = r.tenant_id;

CREATE OR REPLACE VIEW public_lease_refusals WITH (security_barrier = true) AS
SELECT
    f.id,
    f.lease_id,
    f.worker_id,
    f.job_id,
    f.operation,
    f.reason,
    f.refused_at
FROM lease_refusals f
JOIN public_demo_scope s ON s.tenant_id = f.tenant_id;
