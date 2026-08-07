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

Note: this is a new file in a `scripts/` directory that doesn't exist
in the repo yet -- create the directory when you drop this in.
"""

from __future__ import annotations

import sys

from app.presentation.dependencies import get_create_api_key_service


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/issue_api_key.py <label>",
            file=sys.stderr,
        )
        raise SystemExit(1)

    label = sys.argv[1]

    service = get_create_api_key_service()
    issued = service.execute(label=label)

    print(f"Issued API key for '{issued.label}':")
    print(issued.plaintext_key)
    print()
    print(
        "Store this now. It cannot be retrieved again, "
        "only revoked and reissued."
    )


if __name__ == "__main__":
    main()
