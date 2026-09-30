from __future__ import annotations

from collections.abc import Iterable

from app.domain.exceptions.unknown_api_key_scope_error import (
    UnknownApiKeyScopeError,
)

JOBS_EXECUTE = "jobs:execute"
"""
Required to set Job.command when creating a job (ADR 0054).
"""

KNOWN_SCOPES: frozenset[str] = frozenset({JOBS_EXECUTE})


def validate_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """
    Return scopes as a frozenset, rejecting any that are not in
    KNOWN_SCOPES.

    A bare string is rejected outright: iterating one yields
    single characters, which would surface as a confusing
    "unknown scope 'j'" instead of the real mistake.

    Validation happens at issuance only. A stored scope that
    later leaves the vocabulary is simply inert, so loading a
    key never fails because of it.
    """
    if isinstance(scopes, str):
        raise TypeError(
            "scopes must be an iterable of scope names, not a "
            "single string"
        )

    validated = frozenset(scopes)
    unknown = sorted(validated - KNOWN_SCOPES)

    if unknown:
        raise UnknownApiKeyScopeError(unknown[0], KNOWN_SCOPES)

    return validated
