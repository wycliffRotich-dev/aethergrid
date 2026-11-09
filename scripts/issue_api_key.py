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
    python scripts/issue_api_key.py "runner" --tenant acme
    python scripts/issue_api_key.py "runner" --tenant acme --create-tenant

A key belongs to the default tenant unless --tenant names another
(ADR 0090). The name is trimmed and matched exactly, with case. A
tenant that does not exist is an error, and --create-tenant creates
it first. When --tenant is given, the tenant used, and whether it
was created, is reported on standard error, so standard output
still carries only the key.

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
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.domain_error import DomainError
from app.domain.exceptions.tenant_not_found_error import (
    TenantNotFoundError,
)
from app.domain.value_objects.api_key_scope import KNOWN_SCOPES


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


@dataclass(frozen=True, slots=True)
class IssueArgs:
    """
    The parsed command line (ADR 0090).

    Immutable. A field is added only together with the option
    that fills it.
    """

    label: str
    scopes: frozenset[str]
    tenant_name: str | None
    create_tenant: bool


def parse_args(
    argv: Sequence[str] | None = None,
) -> IssueArgs:
    """
    Parse the command line into IssueArgs.

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

    parser.add_argument(
        "--tenant",
        dest="tenant_name",
        metavar="NAME",
        help=(
            "issue the key for the tenant with this name. "
            "Default: the default tenant."
        ),
    )
    parser.add_argument(
        "--create-tenant",
        action="store_true",
        help="create the tenant named by --tenant if it does not exist",
    )

    args = parser.parse_args(argv)

    if args.create_tenant and args.tenant_name is None:
        parser.error("--create-tenant requires --tenant")

    return IssueArgs(
        label=args.label,
        scopes=frozenset(args.scopes or []),
        tenant_name=args.tenant_name,
        create_tenant=args.create_tenant,
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    database_url = os.getenv("NEUROMESH_DATABASE_URL")
    if database_url is not None:
        _confirm_not_test_database(database_url)

    # ADR 0090: the wiring builds the repositories when it is
    # imported, so it is imported here, after the arguments are
    # parsed and the test database guard has run. Usage text and
    # the guard then work without a storage backend.
    from app.presentation.dependencies import (
        get_create_api_key_service,
        get_resolve_tenant_service,
    )

    tenant_id = DEFAULT_TENANT_ID
    if args.tenant_name is not None:
        try:
            resolved = get_resolve_tenant_service().execute(
                args.tenant_name,
                create_if_missing=args.create_tenant,
            )
        except TenantNotFoundError as error:
            raise SystemExit(
                f"error: {error}. Pass --create-tenant to create it."
            ) from error
        except (DomainError, ValueError) as error:
            raise SystemExit(f"error: {error}") from error

        tenant_id = resolved.tenant.id
        verb = "Created" if resolved.created else "Using"
        print(
            f"{verb} tenant '{resolved.tenant.name}' ({tenant_id}).",
            file=sys.stderr,
        )

    service = get_create_api_key_service()
    issued = service.execute(
        label=args.label,
        scopes=args.scopes,
        tenant_id=tenant_id,
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
