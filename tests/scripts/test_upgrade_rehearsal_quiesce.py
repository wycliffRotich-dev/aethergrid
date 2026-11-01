from __future__ import annotations

import pytest

from scripts import upgrade_rehearsal


@pytest.mark.parametrize(
    ("output", "ready"),
    [
        ("1|1\n", True),
        ("3|2\n", True),
        ("0|0\n", False),
        ("0|1\n", False),
    ],
)
def test_assignment_is_ready_when_a_lease_and_a_busy_worker_exist(
    output: str,
    ready: bool,
) -> None:
    assert upgrade_rehearsal.parse_assignment_state(output) is ready


def test_a_lease_before_the_worker_is_saved_is_not_ready() -> None:
    # The lease is saved first and the worker after it. Stopping the API
    # between the two would leave a lease that no worker holds.
    assert upgrade_rehearsal.parse_assignment_state("1|0\n") is False


@pytest.mark.parametrize(
    "output",
    ["", "\n", "1\n", "a|b\n", "1|1|1\n", "-1|1\n"],
)
def test_malformed_assignment_output_is_an_error(output: str) -> None:
    with pytest.raises(ValueError, match="unexpected assignment state"):
        upgrade_rehearsal.parse_assignment_state(output)


def test_the_assignment_query_counts_leases_and_busy_workers() -> None:
    assert upgrade_rehearsal.ASSIGNMENT_SQL == (
        "SELECT (SELECT count(*) FROM leases), "
        "(SELECT count(*) FROM workers WHERE running_job_id IS NOT NULL)"
    )


def test_an_api_that_exited_cleanly_passes() -> None:
    upgrade_rehearsal.require_clean_exit("exited 0\n")


def test_a_killed_api_is_reported_with_its_code() -> None:
    with pytest.raises(RuntimeError, match=r"killed \(exit code 137\)"):
        upgrade_rehearsal.require_clean_exit("exited 137\n")


def test_another_nonzero_exit_is_reported_with_its_code() -> None:
    with pytest.raises(RuntimeError, match="exited with code 2"):
        upgrade_rehearsal.require_clean_exit("exited 2\n")


def test_an_api_that_is_still_running_is_reported() -> None:
    with pytest.raises(RuntimeError, match="did not stop: its status is running"):
        upgrade_rehearsal.require_clean_exit("running 0\n")


@pytest.mark.parametrize(
    "output",
    ["", "exited\n", "exited x\n", "exited 0 0\n"],
)
def test_unexpected_container_output_is_an_error(output: str) -> None:
    with pytest.raises(ValueError, match="unexpected container state"):
        upgrade_rehearsal.require_clean_exit(output)
