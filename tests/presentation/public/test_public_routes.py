"""
ADR 0102, decisions 5 and 7. The five routes of the public app.

Each route is a plain GET that reads a fixed number of rows through the port
and returns them as a list of public models. A query string changes nothing,
so a caller can neither ask for more rows nor draw an error from the
framework. Any failure of the reader, or of the mapping of its rows, ends as
one fixed 503 that holds no part of the failure, and the 503 still carries
the CORS header that the browser needs to read it. The failure is logged for
the operator.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app.presentation.public.app import create_public_app
from app.presentation.public.responses import (
    PublicEventResponse,
    PublicJobResponse,
    PublicLeaseResponse,
    PublicNodeResponse,
    PublicWorkerResponse,
)
from tests.support.public_app import (
    ORIGIN,
    PUBLIC_PATHS,
    FakePublicReader,
    event,
    job,
    lease,
    make_settings,
    node,
    worker,
)

ROW_LIMIT = 100
FIXED_BODY = b'{"error":"unavailable"}'
CANARY = "route-canary-6e1b"


@dataclass(frozen=True)
class Route:
    path: str
    method: str
    rows: str
    make: Callable[[], Any]
    model: type[Any]


ROUTES = [
    Route("/public/nodes", "list_nodes", "nodes", node, PublicNodeResponse),
    Route("/public/jobs", "list_jobs", "jobs", job, PublicJobResponse),
    Route("/public/workers", "list_workers", "workers", worker, PublicWorkerResponse),
    Route("/public/leases", "list_leases", "leases", lease, PublicLeaseResponse),
    Route("/public/events", "list_events", "events", event, PublicEventResponse),
]
EACH_ROUTE = [pytest.param(route, id=route.path) for route in ROUTES]

QUERIES = [
    pytest.param("limit=1", id="a-smaller-limit"),
    pytest.param("limit=abc", id="a-limit-that-is-not-a-number"),
    pytest.param("limit=-1&limit=2", id="a-repeated-limit"),
]

FAILURES = [
    pytest.param(PoolTimeout(CANARY), id="pool-timeout"),
    pytest.param(psycopg.OperationalError(CANARY), id="driver-error"),
    pytest.param(RuntimeError(CANARY), id="runtime-error"),
    pytest.param(ValueError(CANARY), id="value-error"),
]


def _client(reader: FakePublicReader) -> TestClient:
    return TestClient(create_public_app(make_settings(), reader=reader))


@pytest.mark.parametrize("route", EACH_ROUTE)
def test_a_route_returns_its_records_as_json(route: Route) -> None:
    rows = [route.make(), route.make()]
    reader = FakePublicReader(**{route.rows: rows})

    response = _client(reader).get(route.path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        route.model.from_record(row).model_dump(mode="json") for row in rows
    ]


@pytest.mark.parametrize("route", EACH_ROUTE)
def test_a_route_reads_only_its_own_method_once_with_the_row_limit(
    route: Route,
) -> None:
    reader = FakePublicReader(**{route.rows: [route.make()]})

    _client(reader).get(route.path)

    assert reader.calls == [(route.method, ROW_LIMIT)]


@pytest.mark.parametrize("route", EACH_ROUTE)
def test_an_empty_table_is_an_empty_list(route: Route) -> None:
    response = _client(FakePublicReader()).get(route.path)

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize("route", EACH_ROUTE)
def test_a_query_string_changes_nothing(route: Route, query: str) -> None:
    reader = FakePublicReader(**{route.rows: [route.make()]})

    response = _client(reader).get(f"{route.path}?{query}")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert reader.calls == [(route.method, ROW_LIMIT)]


@pytest.mark.parametrize("error", FAILURES)
@pytest.mark.parametrize("route", EACH_ROUTE)
def test_a_reader_failure_is_one_fixed_503(route: Route, error: Exception) -> None:
    reader = FakePublicReader(error=error)

    response = _client(reader).get(route.path, headers={"Origin": ORIGIN})

    assert response.status_code == 503
    assert response.content == FIXED_BODY
    assert response.headers["content-type"] == "application/json"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert CANARY not in response.text
    assert CANARY not in str(response.headers)


def test_a_record_that_cannot_be_mapped_is_a_fixed_503() -> None:
    reader = FakePublicReader(nodes=[node(available_cpu_cores=99)])

    response = _client(reader).get("/public/nodes", headers={"Origin": ORIGIN})

    assert response.status_code == 503
    assert response.content == FIXED_BODY
    assert response.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.parametrize("route", EACH_ROUTE)
def test_a_failure_is_logged_for_the_operator(
    route: Route, caplog: pytest.LogCaptureFixture
) -> None:
    reader = FakePublicReader(error=RuntimeError(CANARY))

    with caplog.at_level(logging.ERROR):
        _client(reader).get(route.path)

    logged = [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR and record.exc_info
    ]

    assert logged, "the failure must reach the log of the operator"


class _Stop(BaseException):
    """Stands for an interrupt, an exit or a cancellation."""


def _contains(error: BaseException, kind: type[BaseException]) -> bool:
    if isinstance(error, kind):
        return True
    return any(_contains(inner, kind) for inner in getattr(error, "exceptions", ()))


@pytest.mark.parametrize("route", EACH_ROUTE)
def test_a_stop_signal_is_not_turned_into_a_503(route: Route) -> None:
    reader = FakePublicReader(error=_Stop())

    with pytest.raises((_Stop, BaseExceptionGroup)) as caught:
        _client(reader).get(route.path)

    assert _contains(caught.value, _Stop)


def test_the_route_table_of_the_tests_equals_the_public_paths() -> None:
    assert {route.path for route in ROUTES} == PUBLIC_PATHS - {"/healthz"}


DATA_PATHS = sorted(PUBLIC_PATHS - {"/healthz"})
FAILED_READ_HEADERS = {"content-length", "content-type", "vary"}


@pytest.mark.parametrize("origin", [True, False], ids=["with-origin", "no-origin"])
@pytest.mark.parametrize("path", DATA_PATHS)
def test_a_failed_read_answers_with_these_headers_and_no_others(
    path: str, origin: bool
) -> None:
    app = create_public_app(
        make_settings(), reader=FakePublicReader(error=RuntimeError(CANARY))
    )
    headers = {"Origin": ORIGIN} if origin else {}

    response = TestClient(app).get(path, headers=headers)

    expected = set(FAILED_READ_HEADERS)
    if origin:
        expected.add("access-control-allow-origin")

    assert response.status_code == 503
    assert response.content == FIXED_BODY
    assert set(response.headers) == expected
    assert all(CANARY not in value for value in response.headers.values())
