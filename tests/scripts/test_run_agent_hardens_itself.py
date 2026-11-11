"""
ADR 0095. The agent holds the API key in its environment, and a job's
command runs below it, so the agent must close its own /proc entry before
it reads the key or builds a client.
"""

from __future__ import annotations

import sys

import pytest

import scripts.run_agent as agent


class _Stop(Exception):
    """Raised by the stub client so main() never reaches the network."""


def test_the_agent_hardens_itself_before_it_builds_its_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    def stub_client(api_key: str) -> object:
        order.append("client")
        raise _Stop

    monkeypatch.setattr(
        agent,
        "make_unreadable_through_proc",
        lambda: order.append("harden"),
        raising=False,
    )
    monkeypatch.setattr(agent, "_client", stub_client)
    monkeypatch.setattr(sys, "argv", ["run_agent.py", "node-1"])
    monkeypatch.setenv("AETHERGRID_API_KEY", "not-a-real-key")

    with pytest.raises(_Stop):
        agent.main()

    assert order == ["harden", "client"]
