from __future__ import annotations

import tomllib
from pathlib import Path

from app.presentation.api import app

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_the_app_reports_the_version_declared_in_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["version"]

    assert app.version == declared, (
        f"the app reports {app.version} but pyproject.toml declares "
        f"{declared}. If the declared version changed, reinstall the "
        "package with: pip install -e '.[dev]'"
    )
