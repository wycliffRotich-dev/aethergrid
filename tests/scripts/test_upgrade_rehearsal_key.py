from __future__ import annotations

import pytest

from scripts import upgrade_rehearsal


def test_the_key_is_read_from_the_marked_line() -> None:
    output = "REHEARSAL_API_KEY=abc123\n"

    assert upgrade_rehearsal.parse_issued_key(output) == "abc123"


def test_log_lines_around_the_marker_are_ignored() -> None:
    output = "INFO starting\nREHEARSAL_API_KEY=abc123\nINFO done\n"

    assert upgrade_rehearsal.parse_issued_key(output) == "abc123"


def test_output_without_the_marker_is_an_error() -> None:
    with pytest.raises(ValueError, match="no issued key"):
        upgrade_rehearsal.parse_issued_key("INFO starting\n")


def test_an_empty_key_is_an_error() -> None:
    with pytest.raises(ValueError, match="empty or contains whitespace"):
        upgrade_rehearsal.parse_issued_key("REHEARSAL_API_KEY=\n")


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (
            "REHEARSAL_API_KEY=s3cret-one\nREHEARSAL_API_KEY=s3cret-two\n",
            "more than one issued key",
        ),
        (
            "REHEARSAL_API_KEY=s3cret with space\n",
            "empty or contains whitespace",
        ),
    ],
)
def test_an_error_never_repeats_the_output(output: str, message: str) -> None:
    with pytest.raises(ValueError, match=message) as error:
        upgrade_rehearsal.parse_issued_key(output)

    assert "s3cret" not in str(error.value)


def test_the_snippet_is_valid_python() -> None:
    compile(upgrade_rehearsal.ISSUE_KEY_SNIPPET, "<snippet>", "exec")


def test_the_snippet_issues_a_default_tenant_key_without_scopes() -> None:
    snippet = upgrade_rehearsal.ISSUE_KEY_SNIPPET

    assert (
        "from app.domain.entities.tenant import DEFAULT_TENANT_ID" in snippet
    )
    assert "get_create_api_key_service().execute(" in snippet
    assert "tenant_id=DEFAULT_TENANT_ID" in snippet
    assert "scopes" not in snippet


def test_the_snippet_prints_the_key_last_on_the_marked_line() -> None:
    last = upgrade_rehearsal.ISSUE_KEY_SNIPPET.strip().splitlines()[-1]

    assert last == (
        f'print("{upgrade_rehearsal.KEY_MARKER}" + issued.plaintext_key)'
    )


def test_a_marker_in_the_middle_of_a_line_is_not_the_key() -> None:
    output = (
        "INFO the marker REHEARSAL_API_KEY=oops is only mentioned here\n"
        "REHEARSAL_API_KEY=real\n"
    )

    assert upgrade_rehearsal.parse_issued_key(output) == "real"
