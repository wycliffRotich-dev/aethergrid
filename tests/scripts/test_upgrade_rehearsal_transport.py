from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.upgrade_rehearsal import ISSUE_KEY_SNIPPET, http_post, issue_key


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, _Server)
        length = int(self.headers.get("Content-Length", "0"))
        server.received.append(
            (
                self.path,
                self.headers.get("Authorization"),
                self.headers.get("Content-Type"),
                self.rfile.read(length),
            )
        )
        self.send_response(server.status)
        self.send_header("Content-Length", str(len(server.reply)))
        self.end_headers()
        self.wfile.write(server.reply)


class _Server(ThreadingHTTPServer):
    status = 201
    reply = b'{"id": "abc"}'

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.received: list[tuple[str, str | None, str | None, bytes]] = []


@pytest.fixture
def server() -> Iterator[_Server]:
    running = _Server()
    thread = threading.Thread(target=running.serve_forever, daemon=True)
    thread.start()
    try:
        yield running
    finally:
        running.shutdown()
        running.server_close()
        thread.join(timeout=5)


def test_the_post_sends_the_key_and_the_json_body(server: _Server) -> None:
    post = http_post(f"http://127.0.0.1:{server.server_port}", "k3y")

    status, body = post("/nodes", {"a": 1})

    assert status == 201
    assert json.loads(body) == {"id": "abc"}
    assert server.received == [
        ("/nodes", "Bearer k3y", "application/json", b'{"a": 1}')
    ]


def test_a_refused_request_returns_its_status_and_body(server: _Server) -> None:
    server.status = 422
    server.reply = b'{"detail": "no"}'
    post = http_post(f"http://127.0.0.1:{server.server_port}", "k3y")

    status, body = post("/workers", {})

    assert (status, json.loads(body)) == (422, {"detail": "no"})


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:80",
        "https://127.0.0.1:8000",
        "http://127.0.0.1:80@example.com",
        "http://127.0.0.1",
        "http://localhost:8000",
        "http://user@127.0.0.1:80",
        "http://127.0.0.1:80/evil",
    ],
)
def test_the_key_is_only_sent_to_the_loopback_address(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        http_post(url, "k")


def _result(
    code: int,
    out: str = "",
    err: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=code, stdout=out, stderr=err
    )


def test_the_key_is_issued_by_running_the_snippet_in_the_old_service() -> None:
    calls: list[Sequence[str]] = []

    def compose(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return _result(0, "log line\nREHEARSAL_API_KEY=abc\n")

    assert issue_key(compose) == "abc"
    assert calls == [
        [
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "neuromesh",
            "python",
            "-c",
            ISSUE_KEY_SNIPPET,
        ]
    ]


def test_a_failed_run_reports_stderr_and_never_the_key() -> None:
    def compose(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _result(1, "REHEARSAL_API_KEY=s3cret\n", "Traceback: boom")

    with pytest.raises(RuntimeError) as raised:
        issue_key(compose)

    message = str(raised.value)
    assert "exit code 1" in message
    assert "boom" in message
    assert "s3cret" not in message


def test_a_successful_run_without_a_key_is_an_error() -> None:
    def compose(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _result(0, "log only\n")

    with pytest.raises(ValueError, match="no issued key"):
        issue_key(compose)
