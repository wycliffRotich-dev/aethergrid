-- ADR 0074: an event carries the tenant of its job.
-- This migration only adds. It leaves the old shape usable, so an
-- older image that writes events without a tenant keeps working
-- after a rollback (ADR 0071, decision 7). A later migration makes
-- the columns required.

ALTER TABLE events
ADD COLUMN IF NOT EXISTS job_id UUID;

ALTER TABLE events
ADD COLUMN IF NOT EXISTS tenant_id UUID
REFERENCES tenants(id);

-- An event takes the tenant of the job its aggregate_id names. The
-- match is made as text, so a value that is not a UUID cannot abort
-- a cast. An event with no matching job stays null and is shown to
-- no tenant. Nothing here falls back to the default tenant.
UPDATE events
SET job_id = jobs.id,
    tenant_id = jobs.tenant_id
FROM jobs
WHERE jobs.id::text = events.aggregate_id
  AND events.job_id IS NULL;

-- The job and the tenant are set together or not at all. A composite
-- foreign key skips a row with a null column, so without this a row
-- with a job and no tenant would not be checked.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'events_job_and_tenant_together'
          AND conrelid = 'events'::regclass
    ) THEN
        ALTER TABLE events
        ADD CONSTRAINT events_job_and_tenant_together
        CHECK ((job_id IS NULL) = (tenant_id IS NULL));
    END IF;
END
$$;

-- The text aggregate_id stays, so the API does not change. When
-- job_id is set it must name the same job.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'events_aggregate_matches_job'
          AND conrelid = 'events'::regclass
    ) THEN
        ALTER TABLE events
        ADD CONSTRAINT events_aggregate_matches_job
        CHECK (job_id IS NULL OR aggregate_id = job_id::text);
    END IF;
END
$$;

-- An event must belong to the tenant of its job, and the database
-- refuses the link even if the application is wrong (ADR 0064,
-- point 7). It points at the unique index on jobs (id, tenant_id).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'events_job_same_tenant'
          AND conrelid = 'events'::regclass
    ) THEN
        ALTER TABLE events
        ADD CONSTRAINT events_job_same_tenant
        FOREIGN KEY (job_id, tenant_id)
        REFERENCES jobs (id, tenant_id);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_events_tenant_occurred_at
ON events (tenant_id, occurred_at);
