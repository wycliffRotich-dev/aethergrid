from __future__ import annotations

from pathlib import Path

from scripts.upgrade_rehearsal import render_override


def test_a_secret_path_with_yaml_syntax_in_it_is_quoted() -> None:
    override = render_override(
        secret_file=Path("/tmp/a run: #1/postgres_password"),
        tag_prefix="rehearsal-abc",
    )

    assert 'file: "/tmp/a run: #1/postgres_password"' in override
