-- ADR 0097: a role for the public demo that can do nothing.
-- ADR 0094 says the public app is not deployed until it has a read-only
-- database role. This migration creates the role and nothing else. It
-- grants the role no table, no schema and no privilege of any kind, so
-- every grant is a later decision with its own review.
--
-- A role belongs to the cluster and not to a schema, so it already exists
-- when a second schema in the same cluster is migrated. An existing role
-- is accepted only if it has no power attribute, holds nothing in this
-- database and has no membership in either direction. Anything else is
-- refused and the role is not changed, because this role is only ever a
-- group role with no power of its own.
--
-- The migration lock is per database, so a runner in another database of
-- the same cluster can create the role between the check and the CREATE.
-- The loser of that race gets a duplicate name error. It then reads the
-- role the winner created and applies the same checks to it.
--
-- It runs in one transaction together with its version row (ADR 0071,
-- decision 4). If the check fails, none of it is applied.

DO $$
DECLARE
    existing record;
    powers text;
    held bigint;
    members bigint;
    memberships bigint;
    holds text;
BEGIN
    SELECT * INTO existing FROM pg_roles WHERE rolname = 'aethergrid_public_read';

    IF NOT FOUND THEN
        BEGIN
            CREATE ROLE aethergrid_public_read
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOREPLICATION NOBYPASSRLS;
            RETURN;
        EXCEPTION WHEN duplicate_object OR unique_violation THEN
            SELECT * INTO existing FROM pg_roles WHERE rolname = 'aethergrid_public_read';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'role aethergrid_public_read could not be created and does not exist';
            END IF;
        END;
    END IF;

    powers := concat_ws(', ',
        CASE WHEN existing.rolcanlogin THEN 'LOGIN' END,
        CASE WHEN existing.rolsuper THEN 'SUPERUSER' END,
        CASE WHEN existing.rolcreatedb THEN 'CREATEDB' END,
        CASE WHEN existing.rolcreaterole THEN 'CREATEROLE' END,
        CASE WHEN existing.rolreplication THEN 'REPLICATION' END,
        CASE WHEN existing.rolbypassrls THEN 'BYPASSRLS' END
    );

    IF powers <> '' THEN
        RAISE EXCEPTION USING
            MESSAGE = 'role aethergrid_public_read already exists with ' || powers,
            HINT = 'The public read role must have no power of its own. Run: ALTER ROLE aethergrid_public_read NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; or drop the role if nothing uses it, then run the migrations again.';
    END IF;

    SELECT count(*) INTO held
    FROM pg_shdepend
    WHERE refclassid = 'pg_authid'::regclass
      AND refobjid = existing.oid
      AND deptype IN ('a', 'o', 'r')
      AND dbid IN (0, (SELECT oid FROM pg_database WHERE datname = current_database()));

    SELECT count(*) INTO members FROM pg_auth_members WHERE roleid = existing.oid;
    SELECT count(*) INTO memberships FROM pg_auth_members WHERE member = existing.oid;

    holds := concat_ws('; ',
        CASE WHEN held > 0 THEN held::text || ' privileges, ownerships or policies' END,
        CASE WHEN members > 0 THEN members::text || ' members' END,
        CASE WHEN memberships > 0 THEN 'membership in ' || memberships::text || ' roles' END
    );

    IF holds <> '' THEN
        RAISE EXCEPTION USING
            MESSAGE = 'role aethergrid_public_read already exists and has been granted access: ' || holds,
            HINT = 'The public read role must hold nothing before this migration runs. See what it holds with: SELECT * FROM pg_shdepend WHERE refobjid = ''aethergrid_public_read''::regrole; and SELECT * FROM pg_auth_members WHERE roleid = ''aethergrid_public_read''::regrole OR member = ''aethergrid_public_read''::regrole; then revoke it or drop the role, and run the migrations again.';
    END IF;
END
$$;
