from __future__ import annotations

import pytest

from app.infrastructure.migrations.runner import (
    Migration,
    MigrationError,
    plan_migrations,
)


def _migration(version: int, checksum: str | None = None) -> Migration:
    return Migration(
        version=version,
        name=f"{version:04d}_m.sql",
        sql="SELECT 1;",
        checksum=checksum or f"sum{version}",
        transactional=True,
    )


def _row(version: int, checksum: str | None = None) -> tuple[int, str, str]:
    return (version, f"{version:04d}_m.sql", checksum or f"sum{version}")


def test_an_empty_history_leaves_every_migration_pending() -> None:
    plan = plan_migrations([], [_migration(1), _migration(2)])

    assert [m.version for m in plan.pending] == [1, 2]
    assert plan.ahead == ()


def test_a_fully_applied_history_has_nothing_pending() -> None:
    plan = plan_migrations([_row(1), _row(2)], [_migration(1), _migration(2)])

    assert plan.pending == ()
    assert plan.ahead == ()


def test_a_partly_applied_history_leaves_only_the_rest_pending() -> None:
    migrations = [_migration(1), _migration(2), _migration(3)]

    plan = plan_migrations([_row(1)], migrations)

    assert [m.version for m in plan.pending] == [2, 3]
    assert plan.ahead == ()


def test_versions_above_the_image_are_ahead_and_nothing_is_pending() -> None:
    recorded = [_row(1), _row(2), _row(3)]

    plan = plan_migrations(recorded, [_migration(1), _migration(2)])

    assert plan.pending == ()
    assert plan.ahead == (3,)


def test_a_checksum_mismatch_below_the_highest_file_is_refused() -> None:
    recorded = [_row(1, "edited"), _row(2)]

    with pytest.raises(MigrationError, match="checksum"):
        plan_migrations(recorded, [_migration(1), _migration(2)])


def test_a_hole_in_the_history_is_refused() -> None:
    recorded = [_row(1), _row(3)]
    migrations = [_migration(1), _migration(2), _migration(3)]

    with pytest.raises(MigrationError, match="hole"):
        plan_migrations(recorded, migrations)


def test_a_hole_above_the_highest_file_is_still_refused() -> None:
    with pytest.raises(MigrationError, match="hole"):
        plan_migrations([_row(1), _row(3)], [_migration(1)])


def test_a_recorded_version_with_no_file_below_the_highest_is_refused() -> None:
    # load_migrations never produces a gap, so the set is built by hand.
    with pytest.raises(MigrationError, match="no file"):
        plan_migrations([_row(1), _row(2)], [_migration(2)])


def test_a_history_with_no_migrations_in_the_image_is_refused() -> None:
    with pytest.raises(MigrationError, match="no migrations"):
        plan_migrations([_row(1)], [])
