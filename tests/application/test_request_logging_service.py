import logging

from app.application.services.request_logging_service import (
    RequestLoggingService,
)

"""
This is the first test file in this codebase to assert on log
output rather than repository state or a raised exception.
pytest's built-in caplog fixture is used rather than mocking
the logging module directly, since RequestLoggingService's own
job is to route a request outcome to the standard library's
logging machinery correctly, not to be a thin wrapper worth
mocking around.
"""


def test_log_completed_request_logs_at_info_for_a_normal_completion(
    caplog,
) -> None:
    service = RequestLoggingService()

    with caplog.at_level(logging.INFO, logger="aethergrid.requests"):
        service.log_completed_request(
            method="GET",
            path="/jobs",
            caller_id="11111111-1111-1111-1111-111111111111",
            status_code=200,
            duration_ms=12.5,
        )

    assert len(caplog.records) == 1

    record = caplog.records[0]

    assert record.levelno == logging.INFO
    assert record.method == "GET"
    assert record.path == "/jobs"
    assert (
        record.caller_id
        == "11111111-1111-1111-1111-111111111111"
    )
    assert record.status_code == 200
    assert record.duration_ms == 12.5


def test_log_completed_request_logs_at_warning_for_401_with_no_caller_id(
    caplog,
) -> None:
    """
    A 401 is logged with caller_id=None, since a request that
    fails authentication never established an authenticated
    identity (see ADR 0022).
    """
    service = RequestLoggingService()

    with caplog.at_level(logging.INFO, logger="aethergrid.requests"):
        service.log_completed_request(
            method="POST",
            path="/jobs",
            caller_id=None,
            status_code=401,
            duration_ms=1.2,
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].caller_id is None
    assert caplog.records[0].status_code == 401


def test_log_completed_request_logs_at_warning_for_429(
    caplog,
) -> None:
    service = RequestLoggingService()

    with caplog.at_level(logging.INFO, logger="aethergrid.requests"):
        service.log_completed_request(
            method="POST",
            path="/jobs",
            caller_id="22222222-2222-2222-2222-222222222222",
            status_code=429,
            duration_ms=0.4,
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].status_code == 429


def test_log_completed_request_logs_at_info_for_handler_raised_404(
    caplog,
) -> None:
    """
    A handler-level failure such as JobNotFoundError producing
    a 404 is still an authenticated, successfully-routed
    request -- it is not a denial in the same sense as 401/429,
    so it stays at INFO rather than WARNING.
    """
    service = RequestLoggingService()

    with caplog.at_level(logging.INFO, logger="aethergrid.requests"):
        service.log_completed_request(
            method="GET",
            path="/jobs/does-not-exist",
            caller_id="33333333-3333-3333-3333-333333333333",
            status_code=404,
            duration_ms=3.1,
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.INFO


def test_log_completed_request_uses_a_custom_logger_when_provided(
    caplog,
) -> None:
    """
    The constructor accepts an explicit logger so a caller is
    not forced to depend on the default "aethergrid.requests"
    logger name.
    """
    custom_logger = logging.getLogger(
        "aethergrid.requests.custom-test-logger"
    )

    service = RequestLoggingService(logger=custom_logger)

    with caplog.at_level(
        logging.INFO,
        logger="aethergrid.requests.custom-test-logger",
    ):
        service.log_completed_request(
            method="GET",
            path="/nodes",
            caller_id="44444444-4444-4444-4444-444444444444",
            status_code=200,
            duration_ms=5.0,
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].name == (
        "aethergrid.requests.custom-test-logger"
    )
