import pytest

from app.domain.entities.job import Job
from app.domain.exceptions.invalid_job_transition import (
    InvalidJobTransition,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


def create_job() -> Job:
    return Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )


def test_job_lifecycle_happy_path() -> None:
    job = create_job()

    job.queue()

    assert job.is_queued()

    job.assign_to(
        NodeId.new(),
    )

    assert job.is_scheduled()

    job.start()

    assert job.is_running()

    job.complete()

    assert job.is_completed()


def test_job_can_be_unscheduled() -> None:
    job = create_job()

    job.queue()

    job.assign_to(
        NodeId.new(),
    )

    job.unschedule()

    assert job.is_queued()


def test_job_can_fail() -> None:
    job = create_job()

    job.queue()

    job.assign_to(
        NodeId.new(),
    )

    job.start()

    job.fail()

    assert job.is_failed()


def test_running_job_can_have_cancellation_requested() -> None:
    job = create_job()

    job.queue()
    job.assign_to(NodeId.new())
    job.start()

    job.request_cancellation()

    assert job.is_cancelling()
    assert job.cancellation_requested_at is not None


def test_cancelling_job_can_be_confirmed_cancelled() -> None:
    job = create_job()

    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.request_cancellation()

    job.confirm_cancelled(exit_code=-15)

    assert job.is_cancelled()
    assert job.exit_code == -15
    assert job.completed_at is not None


def test_cancelling_job_can_still_complete() -> None:
    """
    A job can legitimately finish on its own after
    cancellation was requested but before the kill signal
    reached it (ADR 0029). Whichever actually happens first
    wins -- a real completion is not overwritten by a late
    cancellation.
    """
    job = create_job()

    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.request_cancellation()

    job.complete(exit_code=0)

    assert job.is_completed()
    assert job.exit_code == 0


def test_cancelling_job_can_still_fail() -> None:
    job = create_job()

    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.request_cancellation()

    job.fail(exit_code=1)

    assert job.is_failed()
    assert job.exit_code == 1


def test_queued_job_cannot_have_cancellation_requested() -> None:
    """
    request_cancellation() is only legal from RUNNING.
    Queued and scheduled jobs already have their own
    immediate cancel() path; CANCELLING exists specifically
    for the case where a subprocess is actually executing and
    needs to be signalled asynchronously.
    """
    job = create_job()

    job.queue()

    with pytest.raises(InvalidJobTransition):
        job.request_cancellation()


def test_retry_resets_stale_cancellation_request() -> None:
    """
    A job that reached FAILED via CANCELLING -> FAILED (the
    race where it failed on its own before the kill signal
    landed) must not carry a stale cancellation_requested_at
    into a fresh retry attempt.
    """
    job = create_job()
    job.max_retries = 1

    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.request_cancellation()
    job.fail(exit_code=1)

    job.retry()

    assert job.cancellation_requested_at is None
