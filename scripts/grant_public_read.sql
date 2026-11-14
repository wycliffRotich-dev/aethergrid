-- ADR 0098, decision 7: the grants for the public demo role.
--
-- An operator runs this once on the demo database, as the owner of the
-- views. It is not a migration and must never be placed in the migrations
-- folder. ADR 0097 refuses to migrate a database where the role already
-- holds a privilege, so a grant applied by the migrations would stop the
-- next schema of every database that migrates.
--
-- It gives aethergrid_public_read USAGE on the current schema and SELECT on
-- the five public views, and nothing else. It stops without granting
-- anything if a view is missing, or if the role already holds a privilege
-- on any other relation of the schema. Running it again changes nothing.
--
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/grant_public_read.sql

DO $$
DECLARE
    views constant text[] := ARRAY[
        'public_events',
        'public_jobs',
        'public_leases',
        'public_nodes',
        'public_workers'
    ];
    missing text;
    other text;
    view_name text;
BEGIN
    SELECT string_agg(v, ', ' ORDER BY v) INTO missing
    FROM unnest(views) AS v
    WHERE to_regclass(format('%I.%I', current_schema(), v)) IS NULL;

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'cannot grant: missing view(s) %', missing
            USING HINT = 'Run the migrations up to 0007 first.';
    END IF;

    SELECT string_agg(DISTINCT c.relname, ', ' ORDER BY c.relname) INTO other
    FROM pg_class c
    CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                       ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')) AS p(privilege)
    WHERE c.relnamespace = current_schema()::regnamespace
      AND c.relkind IN ('r', 'v', 'm', 'p')
      AND c.relname <> ALL (views)
      AND has_table_privilege('aethergrid_public_read', c.oid, p.privilege);

    IF other IS NOT NULL THEN
        RAISE EXCEPTION 'cannot grant: aethergrid_public_read already holds a privilege on %', other
            USING HINT = 'The role may hold SELECT on the five public views only. Revoke the others, then run this again.';
    END IF;

    EXECUTE format(
        'GRANT USAGE ON SCHEMA %I TO aethergrid_public_read',
        current_schema()
    );

    FOREACH view_name IN ARRAY views LOOP
        EXECUTE format(
            'GRANT SELECT ON %I.%I TO aethergrid_public_read',
            current_schema(),
            view_name
        );
    END LOOP;
END
$$;
