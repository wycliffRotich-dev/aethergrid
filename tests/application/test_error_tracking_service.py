import logging

import pytest

from app.application.services.error_tracking_service import (
    ErrorTrackingService,
)


def test_capture_error_logs_at_error_with_exc_info(caplog) -> None:
    service = ErrorTrackingService()

    with caplog.at_level(logging.ERROR, logger="aethergrid.errors"):
        try:
            raise ValueError("something broke")
        except ValueError as exc:
            service.capture_error(source="request", exc=exc)

    assert len(caplog.records) == 1

    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert record.source == "request"
    assert record.exception_type == "ValueError"
    assert record.exc_info is not None


def test_capture_error_stores_a_structured_record() -> None:
    service = ErrorTrackingService()

    try:
        raise RuntimeError("cluster tick failed")
    except RuntimeError as exc:
        service.capture_error(
            source="cluster_tick",
            exc=exc,
            context={"tick": 42},
        )

    recent = service.recent_errors()

    assert len(recent) == 1

    record = recent[0]
    assert record.source == "cluster_tick"
    assert record.exception_type == "RuntimeError"
    assert record.exception_message == "cluster tick failed"
    assert "RuntimeError: cluster tick failed" in record.traceback
    assert record.context == {"tick": 42}


def test_capture_error_defaults_context_to_empty_dict() -> None:
    service = ErrorTrackingService()

    try:
        raise ValueError("no context given")
    except ValueError as exc:
        service.capture_error(source="request", exc=exc)

    assert service.recent_errors()[0].context == {}


def test_recent_errors_is_bounded_by_max_stored_errors() -> None:
    """
    Once the store is full, the oldest error is dropped as new
    ones arrive, keeping only the most recent max_stored_errors
    (see ADR 0023: a bounded in-memory store, not an unbounded
    log).
    """
    service = ErrorTrackingService(max_stored_errors=3)

    for i in range(5):
        try:
            raise ValueError(f"error {i}")
        except ValueError as exc:
            service.capture_error(source="request", exc=exc)

    recent = service.recent_errors()

    assert len(recent) == 3
    assert [r.exception_message for r in recent] == [
        "error 2",
        "error 3",
        "error 4",
    ]


def test_capture_error_never_raises_even_if_internal_work_fails() -> None:
    """
    A failure inside error tracking itself must never propagate
    and mask the original exception the caller is handling (see
    ADR 0023).
    """
    service = ErrorTrackingService()

    # Force an internal failure: recent_errors' underlying
    # deque is replaced with something that raises on append.
    class _BrokenDeque:
        def append(self, item: object) -> None:
            raise RuntimeError("storage is broken")

    service._errors = _BrokenDeque()  # type: ignore[assignment]

    try:
        raise ValueError("original failure")
    except ValueError as exc:
        service.capture_error(source="request", exc=exc)


def test_constructor_rejects_non_positive_max_stored_errors() -> None:
    with pytest.raises(ValueError):
        ErrorTrackingService(max_stored_errors=0)
