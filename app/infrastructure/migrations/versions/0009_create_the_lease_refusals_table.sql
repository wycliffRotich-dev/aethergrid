-- ADR 0108: the record of a renew or release call that lease fencing
-- refused for a lease that a recovery path had already reclaimed. It keeps
-- the caller, the operation and the reason beside the reclaim record of
-- the same lease (ADR 0107).
--
-- This migration only adds a table, so an older image keeps working after a
-- rollback (ADR 0071, decision 7). It grants nothing. The public read role
-- has no privilege on this table.
--
-- The reclaim key names the tenant, so the database refuses a record whose
-- reclaim record is missing or is in another tenant. The job key does the
-- same for the job. A record goes when its reclaim record or its job goes.
-- One row is kept for each lease, operation and reason, so repeating a call
-- adds nothing. worker_id has no key: the worker of a refused call may no
-- longer exist, and a record must outlast it.

CREATE TABLE IF NOT EXISTS lease_refusals (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    lease_id UUID NOT NULL,
    worker_id UUID NOT NULL,
    job_id UUID NOT NULL,
    operation TEXT NOT NULL,
    reason TEXT NOT NULL,
    refused_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT lease_refusals_operation_check
        CHECK (operation IN (
            'renew',
            'release'
        )),
    CONSTRAINT lease_refusals_reason_check
        CHECK (reason IN (
            'no_active_lease',
            'lease_not_current'
        )),
    CONSTRAINT lease_refusals_kind_key
        UNIQUE (tenant_id, lease_id, operation, reason),
    CONSTRAINT lease_refusals_reclaim_same_tenant
        FOREIGN KEY (tenant_id, lease_id)
        REFERENCES lease_reclaims (tenant_id, lease_id)
        ON DELETE CASCADE,
    CONSTRAINT lease_refusals_job_same_tenant
        FOREIGN KEY (job_id, tenant_id)
        REFERENCES jobs (id, tenant_id)
        ON DELETE CASCADE
);
