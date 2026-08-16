import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.presentation.request_logging_middleware import (
    RequestLoggingMiddleware,
)


def _build_app() -> FastAPI:
    """
    A minimal standalone FastAPI app, not the real app fixture
    used elsewhere in tests/presentation/, since this test is
    verifying the middleware's own behavior in isolation:
    reading request.state.caller_id, capturing the real status
    code, and logging via RequestLoggingService, rather than
    exercising this system's actual routes and auth flow.
    """
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.post("/authenticated", status_code=201)
    def authenticated(request: Request) -> dict[str, bool]:
        request.state.caller_id = "caller-123"
        return {"ok": True}

    @app.get("/unauthenticated")
    def unauthenticated() -> None:
        raise HTTPException(status_code=401, detail="no key")

    return app


def test_dispatch_logs_real_status_code_and_caller_id_on_success(
    caplog,
) -> None:
    """
    This is the exact case a yield-style FastAPI dependency
    could not observe (see ADR 0022's correction): the true
    status_code (201, not the default) for a successful
    response, captured by middleware rather than a dependency.
    """
    client = TestClient(_build_app())

    with caplog.at_level(
        logging.INFO, logger="aethergrid.requests"
    ):
        response = client.post("/authenticated")

    assert response.status_code == 201
    assert len(caplog.records) == 1

    record = caplog.records[0]
    assert record.status_code == 201
    assert record.caller_id == "caller-123"
    assert record.method == "POST"
    assert record.path == "/authenticated"


def test_dispatch_logs_caller_id_none_when_never_authenticated(
    caplog,
) -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    with caplog.at_level(
        logging.INFO, logger="aethergrid.requests"
    ):
        response = client.get("/unauthenticated")

    assert response.status_code == 401
    assert len(caplog.records) == 1
    assert caplog.records[0].caller_id is None
    assert caplog.records[0].status_code == 401
