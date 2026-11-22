from __future__ import annotations

import threading
import time

import pytest

from app.application.services.job_execution_service import (
    JobExecutionService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.application.workers.worker_execution_loop import (
    WorkerExecutionLoop,
)
from app.domain.entities.lease import Lease
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


class _LosesTheLease(JobExecutionService):
    """
    Runs a step that changes the lease while the command is running,
    then waits so the renewal thread gets its ticks, then runs the
    command as usual.
    """

    def __init__(self, step, pause_seconds: float) -> None:
        super().__init__()
        self._step = step
        self._pause_seconds = pause_seconds

    def execute(self, *args, **kwargs):
        self._step()
        time.sleep(self._pause_seconds)
        return super().execute(*args, **kwargs)


def _scene(
    make_step,
    renewal_interval_seconds: float,
    pause_seconds: float,
    record_release: bool = False,
):
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    worker = make_worker(id=WorkerId.new(), node=node)
    worker.ready()
    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )
    job.queue()
    job.assign_to(node.id)
    node.allocate(job.resources)
    worker.accept(job)

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
    )
    leases = InMemoryLeaseRepository()
    leases.save(lease)
    workers = InMemoryWorkerRepository([worker])
    jobs = InMemoryJobRepository([job])
    events = InMemoryEventRepository()
    recorder = RecordJobEventsService(event_repository=events)

    loop = WorkerExecutionLoop(
        worker_repository=workers,
        job_repository=jobs,
        node_repository=InMemoryNodeRepository([node]),
        lease_repository=leases,
        renew_lease_service=RenewLeaseService(lease_repository=leases),
        release_lease_service=ReleaseLeaseService(
            lease_repository=leases,
            worker_repository=workers,
            record_job_events_service=recorder if record_release else None,
            job_repository=jobs if record_release else None,
        ),
        job_execution_service=_LosesTheLease(
            make_step(leases, lease, worker),
            pause_seconds,
        ),
        record_job_events_service=recorder,
        renewal_interval_seconds=renewal_interval_seconds,
    )
    return loop, worker, job, workers, events


def _reclaimed(leases, lease, worker):
    # Reconciliation reclaimed the job: the lease row is gone and the
    # worker holds no lease at all.
    return lambda: leases.delete_by_id(lease.id, worker.tenant_id)


def _replaced(leases, lease, worker):
    # The worker holds a different lease now.
    return lambda: leases.save(
        Lease.create(
            worker_id=worker.id,
            job_id=lease.job_id,
            tenant_id=worker.tenant_id,
        )
    )


def _assert_nothing_was_recorded(worker, job, workers, events) -> None:
    assert [e.event_type for e in events.list(worker.tenant_id)] == []
    stored = workers.get_by_id(worker.id, worker.tenant_id)
    assert stored is not None
    assert not stored.is_idle()
    assert job.is_running()


def test_a_reclaimed_lease_seen_by_renewal_records_no_outcome() -> None:
    """
    Reconciliation reclaims the job while its command runs, so the
    worker holds no lease. The renewal thread must record that loss
    and the loop must raise it, without writing JobCompleted or
    freeing the worker for a job that was handed to someone else.
    """
    loop, worker, job, workers, events = _scene(_reclaimed, 0.05, 0.4)

    with pytest.raises(NoActiveLeaseError):
        loop.execute(worker.id)

    _assert_nothing_was_recorded(worker, job, workers, events)


def test_a_replaced_lease_seen_by_renewal_records_no_outcome() -> None:
    """
    The renewal thread finds a different lease for its worker. The
    loop raises LeaseNotFoundError and records no outcome.
    """
    loop, worker, job, workers, events = _scene(_replaced, 0.05, 0.4)

    with pytest.raises(LeaseNotFoundError):
        loop.execute(worker.id)

    _assert_nothing_was_recorded(worker, job, workers, events)


def test_a_lease_lost_after_the_last_renewal_records_no_outcome() -> None:
    """
    The lease is lost when no renewal tick runs again. The release at
    the end is then the only check. It refuses, and no outcome event
    may already exist by then.
    """
    loop, worker, job, workers, events = _scene(_reclaimed, 10.0, 0.0)

    with pytest.raises(NoActiveLeaseError):
        loop.execute(worker.id)

    _assert_nothing_was_recorded(worker, job, workers, events)


def test_the_outcome_event_is_written_after_the_outcome_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The release deletes the lease before the outcome is decided, so
    the writes left are the worker, the node and the job. An event
    write that can fail must not sit in front of them, or a failed
    write would leave a released lease and a job that is still
    RUNNING.
    """
    log: list[str] = []

    def record_saves(repository_class, name: str) -> None:
        original = repository_class.save

        def save(self, entity):
            log.append(name)
            return original(self, entity)

        monkeypatch.setattr(repository_class, "save", save)

    record_saves(InMemoryWorkerRepository, "worker")
    record_saves(InMemoryJobRepository, "job")
    record_saves(InMemoryEventRepository, "event")

    loop, worker, job, workers, events = _scene(
        lambda _leases, _lease, _worker: (lambda: None),
        10.0,
        0.0,
    )
    log.clear()

    loop.execute(worker.id)

    assert log[-3:] == ["worker", "job", "event"]


def _spy_on_release(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = ReleaseLeaseService.execute

    def execute(self, *args, **kwargs):
        calls.append("release")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ReleaseLeaseService, "execute", execute)
    return calls


def _spy_on_thread_errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    errors: list[str] = []
    monkeypatch.setattr(
        threading,
        "excepthook",
        lambda args: errors.append(args.exc_type.__name__),
    )
    return errors


def test_the_renewal_thread_ends_cleanly_when_the_lease_was_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The renewal thread that finds no lease records the loss and
    stops. It must not die with an unhandled error, and the loop must
    stop on that verdict without calling the release.
    """
    release_calls = _spy_on_release(monkeypatch)
    thread_errors = _spy_on_thread_errors(monkeypatch)
    loop, worker, job, workers, events = _scene(_reclaimed, 0.05, 0.4)

    with pytest.raises(NoActiveLeaseError):
        loop.execute(worker.id)

    assert thread_errors == []
    assert release_calls == []


def test_the_renewal_thread_ends_cleanly_when_the_lease_was_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The same for a replaced lease: the thread records the loss and
    stops, and the loop does not call the release.
    """
    release_calls = _spy_on_release(monkeypatch)
    thread_errors = _spy_on_thread_errors(monkeypatch)
    loop, worker, job, workers, events = _scene(_replaced, 0.05, 0.4)

    with pytest.raises(LeaseNotFoundError):
        loop.execute(worker.id)

    assert thread_errors == []
    assert release_calls == []


def _count_renewals(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = RenewLeaseService.execute

    def execute(self, *args, **kwargs):
        calls.append("renew")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RenewLeaseService, "execute", execute)
    return calls


def test_the_renewal_thread_stops_after_the_first_lost_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The lease is deleted at the start of the run and the command then
    waits for several renewal intervals. The thread must stop at the
    first refusal, so exactly one renewal is attempted.
    """
    renewals = _count_renewals(monkeypatch)
    loop, worker, job, workers, events = _scene(_reclaimed, 0.05, 0.4)

    with pytest.raises(NoActiveLeaseError):
        loop.execute(worker.id)

    assert renewals == ["renew"]


def test_a_normal_run_records_the_release_before_the_outcome() -> None:
    """
    With a recorder on the release service, a run that keeps its lease
    records LeaseReleased first and the outcome event after it.
    """
    loop, worker, job, workers, events = _scene(
        lambda _leases, _lease, _worker: (lambda: None),
        10.0,
        0.0,
        record_release=True,
    )

    loop.execute(worker.id)

    recorded = [e.event_type for e in events.list(worker.tenant_id)]
    assert recorded == ["LeaseReleased", "JobCompleted"]
