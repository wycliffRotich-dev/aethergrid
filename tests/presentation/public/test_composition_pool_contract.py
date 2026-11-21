"""
ADR 0102, decision 6. The public root cannot import psycopg_pool, so it
types the pool with a small Protocol. Typing alone does not tie that
Protocol to the real pool, and the type check does not read the tests of
the infrastructure layer. This test does: each method the Protocol names
must exist on the real pool and must be callable with no argument. It needs
no database.
"""

from __future__ import annotations

import inspect

from psycopg_pool import ConnectionPool

from app.presentation.public import composition


def _protocol_methods() -> list[str]:
    return sorted(
        name
        for name, value in vars(composition.ClosablePool).items()
        if not name.startswith("_") and callable(value)
    )


def test_the_protocol_names_the_methods_the_lifespan_uses() -> None:
    assert _protocol_methods() == ["close"]


def test_the_real_pool_has_every_method_of_the_protocol() -> None:
    for name in _protocol_methods():
        method = getattr(ConnectionPool, name, None)

        assert callable(method), f"ConnectionPool has no {name}"
        inspect.signature(method).bind(object())
