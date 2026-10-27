from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.migrations.runner import load_migrations

VERSIONS = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "infrastructure"
    / "migrations"
    / "versions"
)

# SHA-256 of each migration file as merged. A database that applied a
# file recorded this checksum and refuses to run if the file changes
# (ADR 0071), so a change is found here in CI and not at deploy time.
# To change the schema, add the next migration. Never edit one of these.
# Add the new file's line here in the pull request that merges it.
EXPECTED_CHECKSUMS = {
    "0001_baseline.sql": (
        "648356d5fb3581b8d917ed62769c33c9ccbd99a7f531ede2c04e0279e7a5b3c5"
    ),
    "0002_give_events_a_tenant.sql": (
        "bb63b2b9e7138d805bf33fd5bfe03e29e7a47caf2b58547345ebb99bbe0e77bd"
    ),
    "0003_require_a_tenant_on_events.sql": (
        "48de6737cff835b75f0e0d739085cceba28ae91ddbd53066e0bda6f9ee27e754"
    ),
    "0004_give_workers_and_leases_a_tenant.sql": (
        "af749a4e76e0b1c05b91dbba0aade603855dc3cc7336479911017875650ed089"
    ),
    "0005_require_a_tenant_on_workers_and_leases.sql": (
        "053c39106e8ad00d5beebcf39adeed1ab1fc449eed3929070bcf5d4c1b4d3ef8"
    ),
}


@pytest.fixture(scope="module")
def on_disk() -> dict[str, str]:
    return {m.name: m.checksum for m in load_migrations(VERSIONS)}


@pytest.mark.parametrize(("name", "checksum"), sorted(EXPECTED_CHECKSUMS.items()))
def test_a_merged_migration_file_is_never_edited(
    on_disk: dict[str, str], name: str, checksum: str
) -> None:
    assert on_disk.get(name) == checksum, (
        f"{name} was changed or removed after it was merged. A database "
        "that applied it refuses to run. Put the change in a new migration."
    )


def test_every_migration_file_is_pinned(on_disk: dict[str, str]) -> None:
    unpinned = sorted(set(on_disk) - set(EXPECTED_CHECKSUMS))

    assert unpinned == [], (
        f"{unpinned} has no entry in EXPECTED_CHECKSUMS. Add its "
        "checksum in the pull request that merges it."
    )
