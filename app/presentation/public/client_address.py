"""
Which address is counted for a request (ADR 0103, decision 5).

With no trusted proxy the socket address is used and X-Forwarded-For is
ignored. With N trusted proxies the Nth entry from the right is used,
because the entries on the right were written by proxies the operator
controls and the caller can write only the left. When the header has fewer
than N entries the request did not pass through every proxy, and the socket
address is used.

The selected value is untrusted text. It is returned for client_key to
validate, so anything that is not an address ends up with the shared key.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.presentation.public.settings import MAX_PROXY_HOPS

_MAX_PORT = 65535
_MAX_PORT_DIGITS = 5


def select_client_address(
    socket_address: str | None,
    forwarded_for_lines: Sequence[str],
    trusted_proxy_hops: int,
) -> str | None:
    if not 0 <= trusted_proxy_hops <= MAX_PROXY_HOPS:
        raise ValueError(
            f"trusted_proxy_hops must be from 0 to {MAX_PROXY_HOPS}."
        )

    if trusted_proxy_hops == 0 or not forwarded_for_lines:
        return socket_address

    # Repeated header lines are one list, in the order they were received,
    # so a line the caller wrote ahead of a proxy's own line stays on the
    # left. Empty entries count, so they cannot shift which entry is chosen.
    entries = ",".join(forwarded_for_lines).split(",")

    if len(entries) < trusted_proxy_hops:
        return socket_address

    return _without_port(entries[-trusted_proxy_hops].strip())


def _without_port(entry: str) -> str:
    """
    Remove the brackets and the port that some proxies add. A form that is
    not exactly one of the accepted shapes is returned unchanged, and
    client_key then gives it the shared key.
    """
    if entry.startswith("["):
        close = entry.find("]")

        if close == -1:
            return entry

        inner = entry[1:close]
        rest = entry[close + 1 :]

        if ":" not in inner:
            return entry

        if rest == "" or (rest.startswith(":") and _is_port(rest[1:])):
            return inner

        return entry

    if entry.count(":") == 1:
        host, port = entry.split(":")

        if _is_port(port):
            return host

    return entry


def _is_port(text: str) -> bool:
    return (
        text.isascii()
        and text.isdigit()
        and len(text) <= _MAX_PORT_DIGITS
        and int(text) <= _MAX_PORT
    )
