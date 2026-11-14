-- ADR 0098, decision 6: choose the tenant the public views show.
--
-- An operator runs this on the demo database, as the owner of the views,
-- with the name of one existing tenant:
--
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v tenant_name=demo \
--         -f scripts/set_public_demo_tenant.sql
--
-- It stops without changing anything if no tenant has that name, or if the
-- views already show a different tenant. Moving the public views from one
-- tenant to another is a deliberate act, so the operator clears the row
-- first, with DELETE FROM public_demo_scope. Running it again for the same
-- tenant changes nothing. It grants nothing to anyone.

-- The name reaches the DO block through a setting that lasts for the
-- session, not for one transaction. psql runs each statement in its own
-- transaction, so a transaction-local setting would be empty by the time
-- the block reads it. The session ends when the script does.
SELECT set_config('aethergrid.tenant_name', :'tenant_name', false);

DO $$
DECLARE
    wanted text := current_setting('aethergrid.tenant_name');
    wanted_id uuid;
    current_id uuid;
    current_name text;
BEGIN
    SELECT id INTO wanted_id FROM tenants WHERE name = wanted;

    IF wanted_id IS NULL THEN
        RAISE EXCEPTION 'cannot set the public tenant: no tenant is named %', wanted;
    END IF;

    SELECT s.tenant_id, t.name INTO current_id, current_name
    FROM public_demo_scope s
    JOIN tenants t ON t.id = s.tenant_id;

    IF current_id IS NULL THEN
        INSERT INTO public_demo_scope (tenant_id) VALUES (wanted_id);
    ELSIF current_id <> wanted_id THEN
        RAISE EXCEPTION 'cannot set the public tenant to %: the views already show %', wanted, current_name
            USING HINT = 'To move them on purpose, run DELETE FROM public_demo_scope and then this script again.';
    END IF;
END
$$;
