from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.application.services.job_execution_service import (
    JobExecutionService,
)


def test_a_job_does_not_import_the_application_from_its_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    ADR 0080. The command starts in the owner's working directory. If
    that directory holds an app package of its own, the supervisor
    must still import the installed one.
    """
    decoy = tmp_path / "decoy" / "app"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text(
        "raise RuntimeError('the job imported a decoy app')\n"
    )
    monkeypatch.chdir(decoy.parent)

    result = JobExecutionService().execute(
        command=["python3", "-c", "pass"],
        timeout=timedelta(seconds=15),
    )

    assert result.succeeded is True
    assert result.exit_code == 0
