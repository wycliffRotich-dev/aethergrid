-- ADR 0107: the record of a lease that a recovery path deleted while it
-- reclaimed a job. A lease row is gone after reclaim, so this table keeps
-- its id, worker, job, tenant and both times.
--
-- This migration only adds a table, so an older image keeps working after a
-- rollback (ADR 0071, decision 7). It grants nothing. The public read role
-- has no privilege on this table (ADR 0107, decision 7).
--
-- The job key names the tenant, so the database refuses a record whose job
-- is missing or is in another tenant, the same way the keys of events and
-- leases do (ADR 0075). A record goes when its job goes. worker_id has no
-- key: deleting a node deletes its workers, and a record must outlast them.

CREATE TABLE IF NOT EXISTS lease_reclaims (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    lease_id UUID NOT NULL,
    worker_id UUID NOT NULL,
    job_id UUID NOT NULL,
    lease_acquired_at TIMESTAMPTZ NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    reclaimed_at TIMESTAMPTZ NOT NULL,
    recovered_by TEXT NOT NULL,
    CONSTRAINT lease_reclaims_recovered_by_check
        CHECK (recovered_by IN (
            'expired_lease',
            'offline_node',
            'worker_registered'
        )),
    CONSTRAINT lease_reclaims_tenant_lease_key
        UNIQUE (tenant_id, lease_id),
    CONSTRAINT lease_reclaims_tenant_fkey
        FOREIGN KEY (tenant_id)
        REFERENCES tenants (id),
    CONSTRAINT lease_reclaims_job_same_tenant
        FOREIGN KEY (job_id, tenant_id)
        REFERENCES jobs (id, tenant_id)
        ON DELETE CASCADE
);
