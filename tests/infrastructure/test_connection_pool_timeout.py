"""
Characterizes the connection pool's timeout for getting a connection
against an unreachable host.

ConnectionPool's own default is 30 seconds (confirmed via
inspect.signature(ConnectionPool.__init__) against the installed
psycopg_pool version). Left unset, as it was in
dependencies.py's _build_repositories(), every caller waiting on
a connection during a database outage inherits that 30 second wait,
which is what let a single reconciliation pass hold a worker thread
for 30 seconds during a real outage (see ADR 0050, ADR 0051).

This test points at a reserved, non-routable address (192.0.2.1,
TEST-NET-1 per RFC 5737) rather than a stopped container, so it needs
no docker compose and fails fast and deterministically in CI.
"""

import time

import pytest
from psycopg_pool import ConnectionPool, PoolTimeout

UNROUTABLE_HOST = "192.0.2.1"
UNROUTABLE_CONNINFO = f"postgresql://user:pass@{UNROUTABLE_HOST}:5432/db"

CURRENT_DEFAULT_TIMEOUT_SECONDS = 30.0
FIXED_TIMEOUT_SECONDS = 5.0
TIMING_TOLERANCE_SECONDS = 2.0


def _time_connection_attempt(timeout: float | None) -> float:
    kwargs = {} if timeout is None else {"timeout": timeout}

    pool = ConnectionPool(
        UNROUTABLE_CONNINFO,
        min_size=0,
        max_size=1,
        open=True,
        kwargs={"connect_timeout": 1},
        **kwargs,
    )

    started = time.monotonic()
    try:
        with pytest.raises(PoolTimeout):
            with pool.connection():
                pass
    finally:
        pool.close()

    return time.monotonic() - started


@pytest.mark.slow
def test_unset_timeout_defaults_to_thirty_seconds() -> None:
    """
    Documents the library default this application was silently
    inheriting before the fix in ADR 0051.
    """
    elapsed = _time_connection_attempt(timeout=None)

    assert abs(elapsed - CURRENT_DEFAULT_TIMEOUT_SECONDS) < TIMING_TOLERANCE_SECONDS, (
        f"expected the unset default to take ~{CURRENT_DEFAULT_TIMEOUT_SECONDS}s, "
        f"took {elapsed:.1f}s instead"
    )


@pytest.mark.slow
def test_explicit_five_second_timeout_is_honored() -> None:
    """
    Confirms the fixed timeout used in dependencies.py actually bounds
    the wait, rather than silently falling back to the library default.
    """
    elapsed = _time_connection_attempt(timeout=FIXED_TIMEOUT_SECONDS)

    assert abs(elapsed - FIXED_TIMEOUT_SECONDS) < TIMING_TOLERANCE_SECONDS, (
        f"expected the explicit {FIXED_TIMEOUT_SECONDS}s timeout to be honored, "
        f"took {elapsed:.1f}s instead"
    )
