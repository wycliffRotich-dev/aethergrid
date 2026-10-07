"""
Bootstrap script for issuing the very first API key.

Run this locally, against whatever backend NEUROMESH_STORAGE_BACKEND
already points at (memory, sqlite, or postgres). This is deliberately
the only way to mint a key without already having one -- every route
under /api-keys requires an existing valid key, so there's no
unauthenticated HTTP path that could do this instead. See
app/presentation/routers/api_keys.py for why that's a router-level
decision, not an oversight.

Usage:
    python scripts/issue_api_key.py "ci-bootstrap"
    python scripts/issue_api_key.py "runner" --scope jobs:execute

A key is issued with no scopes unless --scope is given (ADR
0054). The jobs:execute scope is required to set a job's
command, so grant it deliberately and only to keys that need
it. Scopes can be granted here, with direct repository
access, and never over HTTP.

A key issued here has no recorded issuer (ADR 0056): this
script runs with direct repository access and no
authenticated caller, so there is no key to record as the
one that issued it. Only a key issued through POST /api-keys
records an issuer, letting that issuer later revoke it
without needing keys:manage. A key issued by this script can
only ever be revoked by a caller holding keys:manage.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.api_key_scope import KNOWN_SCOPES
from app.presentation.dependencies import get_create_api_key_service


def _confirm_not_test_database(database_url: str) -> None:
    """
    Refuses to issue a real credential against a database whose
    name suggests it isn't the one the rest of the system reads
    from.

    This exists because a single stray `export` typed into one
    terminal, testing something unrelated, can silently shadow
    the correct NEUROMESH_DATABASE_URL from .bashrc for the rest
    of that session. The script still runs, still prints a real
    plaintext key, still looks completely successful -- and that
    key is valid nowhere the real API, or anything else, ever
    looks. A script that mints real credentials should never
    succeed quietly against the wrong database.
    """
    database_name = database_url.rsplit("/", 1)[-1]
    if "test" in database_name.lower():
        raise RuntimeError(
            f"NEUROMESH_DATABASE_URL points at '{database_name}', "
            f"which looks like a test database. Refusing to issue "
            f"a real credential here.\n\n"
            f"If this is genuinely what you want, override "
            f"explicitly for this one command instead of relying "
            f"on shell state:\n\n"
            f"    NEUROMESH_DATABASE_URL=... python "
            f"scripts/issue_api_key.py <label>"
        )


def parse_args(
    argv: Sequence[str] | None = None,
) -> tuple[str, frozenset[str]]:
    """
    Parse the command line into (label, scopes).

    --scope is repeatable and restricted to the known scope
    vocabulary, so a typo fails here with a clear message
    instead of silently granting nothing. ApiKey.issue()
    enforces the same rule again, since this parser is only
    the friendly front door.
    """
    parser = argparse.ArgumentParser(
        description="Issue an API key.",
    )
    parser.add_argument(
        "label",
        help="human-readable identifier for the caller",
    )
    parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        choices=sorted(KNOWN_SCOPES),
        metavar="SCOPE",
        help=(
            "grant a scope; repeatable. Known scopes: "
            + ", ".join(sorted(KNOWN_SCOPES))
            + ". Default: no scopes."
        ),
    )

    args = parser.parse_args(argv)

    return args.label, frozenset(args.scopes or [])


def main(argv: Sequence[str] | None = None) -> None:
    label, scopes = parse_args(argv)

    database_url = os.getenv("NEUROMESH_DATABASE_URL")
    if database_url is not None:
        _confirm_not_test_database(database_url)

    service = get_create_api_key_service()
    # ADR 0064: a bootstrap key belongs to the default tenant until
    # this script takes a --tenant option.
    issued = service.execute(
        label=label,
        scopes=scopes,
        tenant_id=DEFAULT_TENANT_ID,
    )

    print(f"Issued API key for '{issued.label}':")
    print(issued.plaintext_key)
    print()
    print(f"Scopes: {', '.join(sorted(issued.scopes)) or 'none'}")
    print()
    print(
        "Store this now. It cannot be retrieved again, "
        "only revoked and reissued."
    )


if __name__ == "__main__":
    main()
