from __future__ import annotations

import pytest

from scripts import upgrade_rehearsal


@pytest.mark.parametrize(
    ("output", "port"),
    [
        ("127.0.0.1:49153\n", 49153),
        ("0.0.0.0:32768\n", 32768),
        ("[::]:32769\n", 32769),
    ],
)
def test_the_published_port_is_read_from_the_compose_output(
    output: str,
    port: int,
) -> None:
    assert upgrade_rehearsal.parse_published_port(output) == port


@pytest.mark.parametrize(
    "output",
    ["", "\n", "no port here\n", "127.0.0.1:\n", "127.0.0.1:http\n"],
)
def test_output_without_a_port_is_an_error(output: str) -> None:
    with pytest.raises(ValueError, match="no published port"):
        upgrade_rehearsal.parse_published_port(output)
