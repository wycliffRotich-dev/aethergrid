"""
ADR 0102, decision 6. The real command, uvicorn app.public_main:create_app
--factory, run as a separate process.

The password file does not exist, so startup must stop at once with the
fixed message of read_password_file, before any connection is tried. The
test needs no database. It pins this one failure path only. A start that
serves requests is not run here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"
HOST_CANARY = "canary-host-7f3a.invalid"


def test_startup_without_a_password_file_stops_with_the_fixed_message(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "no-such-password"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": "https://demo.example.org",
        "AETHERGRID_PUBLIC_DATABASE_URL": f"postgresql://aethergrid_public_app@{HOST_CANARY}:1/none",
        SETTING: str(missing),
        "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": "1",
    }

    done = subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.public_main:create_app", "--factory", "--port", "0"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = done.stdout + done.stderr
    last = output.strip().splitlines()[-1]

    assert done.returncode != 0
    assert last == (
        f"RuntimeError: {SETTING} points at '{missing}', "
        "which could not be read: No such file or directory."
    )
    assert HOST_CANARY not in output
    assert "Uvicorn running" not in output
