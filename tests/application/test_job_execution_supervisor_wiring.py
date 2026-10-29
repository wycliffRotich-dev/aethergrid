from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

import app.application.services.job_execution_service as service_module
from app.application.services.job_execution_service import (
    JobExecutionService,
)


def test_a_missing_interpreter_is_a_host_fault_and_not_a_failed_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    ADR 0080. The supervisor is started with the interpreter of this
    process. If that cannot be started, the fault is the host's and
    not the job's, so execute() raises (ADR 0081, Decision 3).
    """
    monkeypatch.setattr(
        service_module.sys, "executable", str(tmp_path / "no-such-python")
    )

    with pytest.raises(FileNotFoundError):
        JobExecutionService().execute(
            command=["python3", "-c", "pass"],
            timeout=timedelta(seconds=15),
        )


@pytest.mark.parametrize("reason", ["cancelled", "lease_lost"])
def test_a_stop_is_acted_on_while_the_supervisor_has_not_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reason: str
) -> None:
    """
    ADR 0080. A supervisor that is slow to report must not delay a
    cancel or a lost lease past one poll interval (ADR 0029, ADR 0044).
    The stub stands in for a supervisor that has not reported yet.
    """
    (tmp_path / "slow_job_supervisor.py").write_text(
        "import time\ntime.sleep(60)\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(
        service_module, "_SUPERVISOR_MODULE", "slow_job_supervisor"
    )
    event = threading.Event()
    event.set()
    events = (
        {"cancel_event": event}
        if reason == "cancelled"
        else {"lease_lost_event": event}
    )

    result = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    ).execute(
        command=["python3", "-c", "pass"],
        timeout=timedelta(seconds=6),
        **events,
    )

    assert result.duration < timedelta(seconds=3)
    assert result.cancelled is (reason == "cancelled")
    assert result.lease_lost is (reason == "lease_lost")
    assert result.timed_out is False
