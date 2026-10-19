-- ADR 0075, slice 1: workers and leases carry a tenant.
-- This migration only adds. The single column keys stay and the tenant
-- stays nullable, so an older image that writes a worker or a lease with
-- no tenant keeps working after a rollback (ADR 0071, decision 7). A
-- composite key skips a row with a null column, so such a row is simply
-- not checked. A later migration makes the tenant required and drops
-- the single column keys.
--
-- It runs in one transaction with its version row (ADR 0071, decision
-- 4). Existing rows that cross a tenant make a composite key fail to
-- apply, and the whole migration is undone.

ALTER TABLE workers
ADD COLUMN IF NOT EXISTS tenant_id UUID
REFERENCES tenants(id);

ALTER TABLE leases
ADD COLUMN IF NOT EXISTS tenant_id UUID
REFERENCES tenants(id);

-- A worker takes the tenant of its node, then a lease takes the tenant
-- of its worker, in that order. Nothing falls back to the default
-- tenant. Every worker has a node and every lease has a worker, so no
-- row is left without an owner.
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

-- The composite keys of leases point at this index. The ones for nodes
-- and jobs already exist in the baseline.
CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_id_tenant
ON workers (id, tenant_id);

-- A worker must be in the tenant of its node.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'workers_node_same_tenant'
          AND conrelid = 'workers'::regclass
    ) THEN
        ALTER TABLE workers
        ADD CONSTRAINT workers_node_same_tenant
        FOREIGN KEY (node_id, tenant_id)
        REFERENCES nodes (id, tenant_id)
        ON DELETE CASCADE;
    END IF;
END
$$;

-- A worker must run a job in its own tenant. ON DELETE SET NULL names
-- the column, so deleting a job clears the link and never tries to null
-- the tenant (the column list form needs PostgreSQL 15, and compose
-- pins 16). A worker with no job has a NULL running_job_id and is not
-- checked.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'workers_running_job_same_tenant'
          AND conrelid = 'workers'::regclass
    ) THEN
        ALTER TABLE workers
        ADD CONSTRAINT workers_running_job_same_tenant
        FOREIGN KEY (running_job_id, tenant_id)
        REFERENCES jobs (id, tenant_id)
        ON DELETE SET NULL (running_job_id);
    END IF;
END
$$;

-- A lease must be in the tenant of its worker and of its job.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'leases_worker_same_tenant'
          AND conrelid = 'leases'::regclass
    ) THEN
        ALTER TABLE leases
        ADD CONSTRAINT leases_worker_same_tenant
        FOREIGN KEY (worker_id, tenant_id)
        REFERENCES workers (id, tenant_id)
        ON DELETE CASCADE;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'leases_job_same_tenant'
          AND conrelid = 'leases'::regclass
    ) THEN
        ALTER TABLE leases
        ADD CONSTRAINT leases_job_same_tenant
        FOREIGN KEY (job_id, tenant_id)
        REFERENCES jobs (id, tenant_id)
        ON DELETE CASCADE;
    END IF;
END
$$;
