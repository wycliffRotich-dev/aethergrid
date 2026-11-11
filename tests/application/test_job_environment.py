from __future__ import annotations

from app.application.services.job_supervisor import job_environment

PASSTHROUGH = "NEUROMESH_JOB_ENV_PASSTHROUGH"


def test_only_the_allowlist_is_kept() -> None:
    source = {"PATH": "/bin", "HOME": "/home/job", "A_SECRET": "s"}

    assert job_environment(source) == {"PATH": "/bin", "HOME": "/home/job"}


def test_a_variable_the_operator_names_is_passed_through() -> None:
    source = {
        "PATH": "/bin",
        "CUDA_VISIBLE_DEVICES": "0",
        PASSTHROUGH: "CUDA_VISIBLE_DEVICES",
    }

    assert job_environment(source)["CUDA_VISIBLE_DEVICES"] == "0"


def test_the_passthrough_setting_itself_is_not_passed() -> None:
    source = {"A": "1", PASSTHROUGH: "A"}

    assert PASSTHROUGH not in job_environment(source)


def test_a_variable_that_is_not_named_stays_behind() -> None:
    source = {"A": "1", "B": "2", PASSTHROUGH: "A"}

    assert "B" not in job_environment(source)


def test_blank_entries_and_spaces_are_ignored() -> None:
    source = {"A": "1", PASSTHROUGH: " A , ,, "}

    assert job_environment(source) == {"A": "1"}


def test_a_named_variable_that_is_not_set_is_skipped() -> None:
    source = {PASSTHROUGH: "MISSING"}

    assert job_environment(source) == {}
