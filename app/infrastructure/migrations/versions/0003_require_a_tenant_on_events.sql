-- ADR 0074, slice 3: an event must have a job and a tenant.
-- Migration 0002 only added the columns, so an older image could keep
-- writing events without them. This migration makes them required. It
-- ships in a later release than 0002, after no older image runs
-- (ADR 0071, decision 7).
--
-- It runs in one transaction together with its version row (ADR 0071,
-- decision 4). If any step fails, none of it is applied.

-- An event an older image wrote after 0002 has no job and no tenant.
-- It takes the tenant of the job its aggregate_id names. The match is
-- made as text, as in 0002, so a value that is not a UUID cannot abort
-- a cast. Nothing here falls back to the default tenant.
UPDATE events
SET job_id = jobs.id,
    tenant_id = jobs.tenant_id
FROM jobs
WHERE jobs.id::text = events.aggregate_id
  AND events.job_id IS NULL;

-- An event that names no job cannot be given a tenant, and nothing
-- guesses one. The migration stops and the transaction rolls back, so
-- the backfill above is undone with it.
DO $$
DECLARE
    orphans bigint;
BEGIN
    SELECT count(*) INTO orphans FROM events WHERE job_id IS NULL;

    IF orphans > 0 THEN
        RAISE EXCEPTION USING
            MESSAGE = orphans::text
                || ' events name no job and cannot be given a tenant',
            HINT = 'Remove or repair these events, then run the migrations again.';
    END IF;
END
$$;

ALTER TABLE events
ALTER COLUMN job_id SET NOT NULL;

ALTER TABLE events
ALTER COLUMN tenant_id SET NOT NULL;
