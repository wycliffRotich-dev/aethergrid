from __future__ import annotations

import ast
from pathlib import Path

# Connection attributes whose value persists on a pooled connection
# after it is returned, so the next borrower inherits the change
# (ADR 0072). Ask for the behaviour on a cursor, or configure it on
# the pool, instead of assigning it on a borrowed connection.
FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "row_factory",
        "autocommit",
        "isolation_level",
        "read_only",
        "deferrable",
    }
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INFRASTRUCTURE_ROOT = REPOSITORY_ROOT / "app" / "infrastructure"

# create_connection builds the sqlite3 connection it configures and
# nothing pools it, so no other borrower can inherit the setting.
ALLOWED_FILES = frozenset(
    {"app/infrastructure/repositories/sqlite_connection.py"}
)


def find_connection_state_changes(source: str) -> list[tuple[int, str]]:
    """Return (line, attribute) for each assignment of connection state."""
    found: list[tuple[int, str]] = []

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for part in ast.walk(target):
                    if (
                        isinstance(part, ast.Attribute)
                        and part.attr in FORBIDDEN_ATTRIBUTES
                    ):
                        found.append((node.lineno, part.attr))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            target = node.target
            if (
                isinstance(target, ast.Attribute)
                and target.attr in FORBIDDEN_ATTRIBUTES
            ):
                found.append((node.lineno, target.attr))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in FORBIDDEN_ATTRIBUTES
        ):
            found.append((node.lineno, str(node.args[1].value)))

    return found


def test_the_detector_flags_an_assignment_to_connection_state() -> None:
    assert find_connection_state_changes("conn.row_factory = dict_row\n") == [
        (1, "row_factory")
    ]
    assert find_connection_state_changes("conn.autocommit = True\n") == [
        (1, "autocommit")
    ]


def test_the_detector_flags_setattr_on_connection_state() -> None:
    source = 'setattr(conn, "row_factory", dict_row)\n'

    assert find_connection_state_changes(source) == [(1, "row_factory")]


def test_the_detector_ignores_a_row_factory_passed_to_a_cursor() -> None:
    source = "conn.cursor(row_factory=dict_row).execute('SELECT 1')\n"

    assert find_connection_state_changes(source) == []


def test_the_allowed_files_still_exist() -> None:
    for relative in ALLOWED_FILES:
        assert (REPOSITORY_ROOT / relative).is_file(), relative


def test_infrastructure_never_mutates_pooled_connection_state() -> None:
    assert INFRASTRUCTURE_ROOT.is_dir(), INFRASTRUCTURE_ROOT

    offenders = []
    for path in sorted(INFRASTRUCTURE_ROOT.rglob("*.py")):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if relative in ALLOWED_FILES:
            continue
        for line, attribute in find_connection_state_changes(
            path.read_text()
        ):
            offenders.append(f"{relative}:{line} assigns .{attribute}")

    assert not offenders, "\n".join(offenders)
