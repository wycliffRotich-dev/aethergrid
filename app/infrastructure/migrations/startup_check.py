"""Check the schema version when the application starts (ADR 0072).

The check only reads. It never creates schema_migrations, because a
database that has not been migrated must be reported, not repaired.
"""

from __future__ import annotations

from collections.abc import Sequence

from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from app.infrastructure.migrations.runner import (
    Migration,
    MigrationError,
    plan_migrations,
)


def check_schema(
    pool: ConnectionPool,
    migrations: Sequence[Migration],
) -> tuple[int, ...]:
    """
    Compare the database behind pool with the migration set and return
    the recorded versions that are ahead of it.

    Raises MigrationError when the bookkeeping table is missing, when
    migrations are still pending (the message names their files), and for
    every refusal plan_migrations makes: a hole in the history, a recorded
    version below the highest that has no file, a changed checksum, or a
    history against a set with no migrations.

    The table is found with an unqualified name, so it resolves through
    the search path the pool's connections use, which is the one the
    runner used.
    """
    with pool.connection() as conn:
        # Ask for tuples on this cursor so the check does not depend on
        # the row factory the connection carries. The pool does not reset
        # connection state, so a borrowed connection can arrive with
        # another caller's setting (ADR 0072).
        with conn.cursor(row_factory=tuple_row) as cursor:
            exists = cursor.execute(
                "SELECT to_regclass('schema_migrations') IS NOT NULL"
            ).fetchone()
            if exists is None or not exists[0]:
                raise MigrationError(
                    "schema_migrations does not exist: run the migrations "
                    "before starting the application"
                )
            recorded = cursor.execute(
                "SELECT version, name, checksum FROM schema_migrations "
                "ORDER BY version"
            ).fetchall()

    plan = plan_migrations(recorded, migrations)
    if plan.pending:
        names = ", ".join(migration.name for migration in plan.pending)
        raise MigrationError(
            f"the database is behind this build: not applied: {names}. "
            "Run the migrations before starting the application"
        )
    return plan.ahead
