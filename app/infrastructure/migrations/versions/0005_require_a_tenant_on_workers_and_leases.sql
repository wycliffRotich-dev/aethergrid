-- ADR 0075, slice 2: a worker and a lease must have a tenant.
-- Migration 0004 only added the columns, so an older image could keep
-- writing rows without one. This migration makes them required and drops
-- the single column keys that the composite keys of 0004 replace. It
-- ships in a later release than 0004, after no older image runs
-- (ADR 0071, decision 7; ADR 0075, decision 12).
--
-- It runs in one transaction together with its version row (ADR 0071,
-- decision 4). If any step fails, none of it is applied.

-- A worker an older image wrote after 0004 has no tenant. It takes the
-- tenant of its node, then a lease takes the tenant of its worker, in
-- that order. Nothing falls back to the default tenant.
UPDATE workers
SET tenant_id = nodes.tenant_id
FROM nodes
WHERE nodes.id = workers.node_id
  AND workers.tenant_id IS NULL;

UPDATE leases
SET tenant_id = workers.tenant_id
FROM workers
WHERE workers.id = leases.worker_id
  AND leases.tenant_id IS NULL;

-- A row that is still without a tenant cannot be given one, and nothing
-- guesses one. The migration stops and the transaction rolls back, so
-- the backfill above is undone with it.
DO $$
DECLARE
    orphan_workers bigint;
    orphan_leases bigint;
BEGIN
    SELECT count(*) INTO orphan_workers FROM workers WHERE tenant_id IS NULL;
    SELECT count(*) INTO orphan_leases FROM leases WHERE tenant_id IS NULL;

    IF orphan_workers > 0 OR orphan_leases > 0 THEN
        RAISE EXCEPTION USING
            MESSAGE = orphan_workers::text || ' workers and '
                || orphan_leases::text
                || ' leases have no tenant and cannot be given one',
            HINT = 'Find them with: SELECT id FROM workers WHERE tenant_id IS NULL; and SELECT id FROM leases WHERE tenant_id IS NULL; then repair or remove them and run the migrations again.';
    END IF;
END
$$;

ALTER TABLE workers
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE leases
ALTER COLUMN tenant_id SET NOT NULL;

-- The composite keys of 0004 now cover every row, so the single column
-- keys are redundant. IF EXISTS because a migrated database may differ
-- from a fresh one. The unique keys on leases.worker_id and
-- leases.job_id stay.
ALTER TABLE workers DROP CONSTRAINT IF EXISTS workers_node_id_fkey;
ALTER TABLE workers DROP CONSTRAINT IF EXISTS workers_running_job_id_fkey;
ALTER TABLE leases DROP CONSTRAINT IF EXISTS leases_worker_id_fkey;
ALTER TABLE leases DROP CONSTRAINT IF EXISTS leases_job_id_fkey;
