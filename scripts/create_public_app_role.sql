-- ADR 0099: the login role of the public app.
--
-- An operator runs this once on the demo database, as the owner of the
-- views, after scripts/grant_public_read.sql. It is not a migration and
-- must never be placed in the migrations folder.
--
--     AETHERGRID_PUBLIC_APP_PASSWORD_FILE=/run/secrets/public_app_password \
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--         -v connection_limit=10 -v statement_timeout=5s \
--         -f scripts/create_public_app_role.sql
--
-- The password comes from the file that AETHERGRID_PUBLIC_APP_PASSWORD_FILE
-- names. psql reads it through a backtick command, so this script depends
-- on a shell and trusts the path. The path is read from the environment by
-- that shell, so it is never part of the SQL text. The password is never
-- taken from the command line and never printed. An empty file is refused,
-- because an empty password would leave the role with no password at all.
--
-- It creates aethergrid_public_app, or updates its password and limits if
-- the role exists. It stops without changing anything if the role has a
-- power attribute, a member, a membership, or a privilege on any relation of
-- the schema other than the five public views. It gives the role USAGE on
-- the schema and SELECT on the five views, and nothing else.

\set QUIET on
\set password `cat "$AETHERGRID_PUBLIC_APP_PASSWORD_FILE"`

-- The result of this call is the password, so it goes nowhere.
\o /dev/null
SELECT set_config('aethergrid.app_password', :'password', false);
\o

DO $$
BEGIN
    IF current_setting('aethergrid.app_password') = '' THEN
        RAISE EXCEPTION 'cannot create the public app role: the password file is empty or unreadable'
            USING HINT = 'Set AETHERGRID_PUBLIC_APP_PASSWORD_FILE to a file that holds the password.';
    END IF;
END
$$;
SELECT set_config('aethergrid.app_limit', :'connection_limit', false);
SELECT set_config('aethergrid.app_timeout', :'statement_timeout', false);

DO $$
DECLARE
    views constant text[] := ARRAY[
        'public_events',
        'public_jobs',
        'public_leases',
        'public_nodes',
        'public_workers'
    ];
    existing record;
    powers text;
    other text;
    members bigint;
    memberships bigint;
    missing text;
    view_name text;
BEGIN
    SELECT string_agg(v, ', ' ORDER BY v) INTO missing
    FROM unnest(views) AS v
    WHERE to_regclass(format('%I.%I', current_schema(), v)) IS NULL;

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'cannot create the public app role: missing view(s) %', missing
            USING HINT = 'Run the migrations up to 0007 first.';
    END IF;

    SELECT * INTO existing FROM pg_roles WHERE rolname = 'aethergrid_public_app';

    IF FOUND THEN
        powers := concat_ws(', ',
            CASE WHEN existing.rolsuper THEN 'SUPERUSER' END,
            CASE WHEN existing.rolcreatedb THEN 'CREATEDB' END,
            CASE WHEN existing.rolcreaterole THEN 'CREATEROLE' END,
            CASE WHEN existing.rolreplication THEN 'REPLICATION' END,
            CASE WHEN existing.rolbypassrls THEN 'BYPASSRLS' END
        );

        IF powers <> '' THEN
            RAISE EXCEPTION 'aethergrid_public_app already exists with %', powers
                USING HINT = 'The public app role must have no power of its own. Run: ALTER ROLE aethergrid_public_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; or drop the role, then run this again.';
        END IF;

        SELECT count(*) INTO members FROM pg_auth_members WHERE roleid = existing.oid;
        SELECT count(*) INTO memberships FROM pg_auth_members WHERE member = existing.oid;

        IF members > 0 OR memberships > 0 THEN
            RAISE EXCEPTION 'aethergrid_public_app already exists with % members and % memberships', members, memberships
                USING HINT = 'The public app role must not be a member of any role and must have no member.';
        END IF;

        SELECT string_agg(DISTINCT c.relname, ', ' ORDER BY c.relname) INTO other
        FROM pg_class c
        CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                           ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')) AS p(privilege)
        WHERE c.relnamespace = current_schema()::regnamespace
          AND c.relkind IN ('r', 'v', 'm', 'p')
          AND c.relname <> ALL (views)
          AND has_table_privilege('aethergrid_public_app', c.oid, p.privilege);

        IF other IS NOT NULL THEN
            RAISE EXCEPTION 'aethergrid_public_app already holds a privilege on %', other
                USING HINT = 'The role may hold SELECT on the five public views only. Revoke the others, then run this again.';
        END IF;
    ELSE
        CREATE ROLE aethergrid_public_app
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;

    SET LOCAL password_encryption = 'scram-sha-256';

    EXECUTE format(
        'ALTER ROLE aethergrid_public_app PASSWORD %L CONNECTION LIMIT %s',
        current_setting('aethergrid.app_password'),
        current_setting('aethergrid.app_limit')::integer
    );
    EXECUTE format(
        'ALTER ROLE aethergrid_public_app SET statement_timeout = %L',
        current_setting('aethergrid.app_timeout')
    );
    EXECUTE format(
        'GRANT USAGE ON SCHEMA %I TO aethergrid_public_app',
        current_schema()
    );

    FOREACH view_name IN ARRAY views LOOP
        EXECUTE format(
            'GRANT SELECT ON %I.%I TO aethergrid_public_app',
            current_schema(),
            view_name
        );
    END LOOP;
END
$$;

SELECT set_config('aethergrid.app_password', '', false);
