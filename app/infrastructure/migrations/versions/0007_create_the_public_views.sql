-- ADR 0098: the public demo reads views and nothing else.
-- This migration creates five views with named columns and a table that
-- says which tenant they show. It grants nothing to anyone. The operator
-- runs scripts/grant_public_read.sql on the demo database, because ADR
-- 0097 refuses to migrate a database where the role already holds a
-- privilege, so a grant here would break the next schema of that database.
--
-- Each view runs with the rights of its owner, so the role needs no
-- privilege on any base table. Each is security_barrier, so a function a
-- caller puts in a query cannot see a row before the tenant filter has
-- removed it. A column added to a table later is not public until a new
-- migration adds it to its view.
--
-- public_demo_scope holds at most one row. With no row the views are empty.
--
-- It runs in one transaction together with its version row (ADR 0071,
-- decision 4). If any step fails, none of it is applied.

CREATE TABLE IF NOT EXISTS public_demo_scope (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    tenant_id uuid NOT NULL REFERENCES tenants(id)
);

CREATE OR REPLACE VIEW public_nodes WITH (security_barrier = true) AS
SELECT
    n.id,
    n.name,
    n.capacity_cpu_cores,
    n.capacity_memory_mib,
    n.capacity_vram_mib,
    n.available_cpu_cores,
    n.available_memory_mib,
    n.available_vram_mib,
    n.last_seen_at,
    n.draining
FROM nodes n
JOIN public_demo_scope s ON s.tenant_id = n.tenant_id;

CREATE OR REPLACE VIEW public_jobs WITH (security_barrier = true) AS
SELECT
    j.id,
    j.cpu_cores,
    j.memory_mib,
    j.vram_mib,
    j.priority,
    j.max_retries,
    j.retry_count,
    j.status,
    j.assigned_node_id,
    j.submitted_at,
    j.started_at,
    j.completed_at,
    j.execution_timeout_seconds
FROM jobs j
JOIN public_demo_scope s ON s.tenant_id = j.tenant_id;

CREATE OR REPLACE VIEW public_workers WITH (security_barrier = true) AS
SELECT
    w.id,
    w.node_id,
    w.status,
    w.running_job_id,
    w.last_seen_at
FROM workers w
JOIN public_demo_scope s ON s.tenant_id = w.tenant_id;

CREATE OR REPLACE VIEW public_leases WITH (security_barrier = true) AS
SELECT
    l.id,
    l.worker_id,
    l.job_id,
    l.acquired_at,
    l.expires_at
FROM leases l
JOIN public_demo_scope s ON s.tenant_id = l.tenant_id;

CREATE OR REPLACE VIEW public_events WITH (security_barrier = true) AS
SELECT
    e.id,
    e.aggregate_id,
    e.aggregate_type,
    e.event_type,
    e.occurred_at
FROM events e
JOIN public_demo_scope s ON s.tenant_id = e.tenant_id;
