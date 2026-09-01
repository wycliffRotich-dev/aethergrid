-- NeuroMesh Postgres schema.
-- Plain SQL, no ORM/migration-tool magic, by design --
-- see ADR 0004 (psycopg over SQLAlchemy).

CREATE TABLE IF NOT EXISTS nodes (
    id                    UUID PRIMARY KEY,
    name                  TEXT NOT NULL,
    capacity_cpu_cores    INTEGER NOT NULL,
    capacity_memory_mib   INTEGER NOT NULL,
    capacity_vram_mib     INTEGER NOT NULL,
    available_cpu_cores   INTEGER NOT NULL,
    available_memory_mib  INTEGER NOT NULL,
    available_vram_mib    INTEGER NOT NULL,
    labels                JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at          TIMESTAMPTZ NOT NULL,
    draining              BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS jobs (
    id                 UUID PRIMARY KEY,
    cpu_cores          INTEGER NOT NULL,
    memory_mib         INTEGER NOT NULL,
    vram_mib           INTEGER NOT NULL DEFAULT 0,
    priority           INTEGER NOT NULL DEFAULT 0,
    constraints        JSONB NOT NULL DEFAULT '{}'::jsonb,
    max_retries        INTEGER NOT NULL DEFAULT 0,
    retry_count        INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL,
    assigned_node_id   UUID REFERENCES nodes(id) ON DELETE SET NULL,
    submitted_at       TIMESTAMPTZ NOT NULL,
    started_at         TIMESTAMPTZ,
    completed_at       TIMESTAMPTZ,
    command            JSONB,
    exit_code          INTEGER,
    cancellation_requested_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workers (
    id                UUID PRIMARY KEY,
    node_id           UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    status            TEXT NOT NULL,
    managed_by        TEXT NOT NULL DEFAULT 'DASHBOARD',
    running_job_id    UUID REFERENCES jobs(id) ON DELETE SET NULL,
    last_seen_at      TIMESTAMPTZ NOT NULL
);

-- CREATE TABLE IF NOT EXISTS is a no-op against a database that
-- already has a workers table from before managed_by existed, so
-- this ALTER covers any environment being upgraded in place rather
-- than created fresh (this project has no migration framework by
-- design, see the header above).
ALTER TABLE workers
ADD COLUMN IF NOT EXISTS managed_by TEXT NOT NULL DEFAULT 'DASHBOARD';

-- Same rationale as the managed_by ALTER above: covers any
-- environment created before ADR 0029 introduced cancellation,
-- whose jobs table predates this column.
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS cancellation_requested_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS leases (
    id                UUID PRIMARY KEY,
    worker_id         UUID NOT NULL UNIQUE REFERENCES workers(id) ON DELETE CASCADE,
    job_id            UUID NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
    acquired_at       TIMESTAMPTZ NOT NULL,
    expires_at        TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id                UUID PRIMARY KEY,
    aggregate_id      TEXT NOT NULL,
    aggregate_type    TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    occurred_at       TIMESTAMPTZ NOT NULL,
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
ON jobs (status);

CREATE INDEX IF NOT EXISTS idx_nodes_draining
ON nodes (draining);

CREATE INDEX IF NOT EXISTS idx_workers_status
ON workers (status);

CREATE INDEX IF NOT EXISTS idx_leases_expires_at
ON leases (expires_at);

CREATE INDEX IF NOT EXISTS idx_events_aggregate_id
ON events (aggregate_id);

CREATE INDEX IF NOT EXISTS idx_events_occurred_at
ON events (occurred_at);
CREATE TABLE IF NOT EXISTS api_keys (
    id                UUID PRIMARY KEY,
    key_hash          TEXT NOT NULL,
    label             TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    revoked_at        TIMESTAMPTZ,
    last_used_at      TIMESTAMPTZ
);

-- get_by_hash() runs on every authenticated request. Without this
-- index it's a sequential scan per call, the one place in this
-- schema where a missing index turns into request latency, not
-- just a slow report query.
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_key_hash
ON api_keys (key_hash);
