from __future__ import annotations

import threading
import time
from datetime import timedelta

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
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
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


def _make_worker_and_job(
    command: list[str] | None = None,
) -> tuple[Worker, Job, Node]:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    worker.ready()

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        command=command,
    )

    # Respect the state machine, and actually allocate the node's
    # resources the way AssignWorkerService does in production --
    # without this, node.available never shrinks, and a test could
    # pass even if release() were never called at all.
    job.queue()
    job.assign_to(node.id)
    node.allocate(job.resources)

    worker.accept(job)

    return worker, job, node


def _build_loop(
    worker: Worker,
    job: Job,
    node: Node,
    record_job_events_service: RecordJobEventsService | None = None,
) -> tuple[
    WorkerExecutionLoop,
    InMemoryWorkerRepository,
    InMemoryJobRepository,
    InMemoryNodeRepository,
    InMemoryLeaseRepository,
]:
    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    node_repository = InMemoryNodeRepository([node])

    renew_lease_service = RenewLeaseService(
        lease_repository=lease_repository,
    )

    release_lease_service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    job_execution_service = JobExecutionService()

    loop = WorkerExecutionLoop(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        renew_lease_service=renew_lease_service,
        release_lease_service=release_lease_service,
        job_execution_service=job_execution_service,
        record_job_events_service=record_job_events_service,
    )

    return loop, worker_repository, job_repository, node_repository, lease_repository
    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    node_repository = InMemoryNodeRepository([node])

    renew_lease_service = RenewLeaseService(
        lease_repository=lease_repository,
    )

    release_lease_service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    job_execution_service = JobExecutionService()

    loop = WorkerExecutionLoop(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        renew_lease_service=renew_lease_service,
        release_lease_service=release_lease_service,
        job_execution_service=job_execution_service,
    )

    return loop, worker_repository, job_repository, node_repository, lease_repository


def test_run_once_with_no_command_completes_successfully() -> None:
    """
    A job with no command (today's API default) is treated
    as an immediate no-op success, matching
    JobExecutionService's own behavior for command=None.
    """
    worker, job, node = _make_worker_and_job()

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node)
    )

    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()
    assert saved_worker.running_job is None

    assert saved_job is not None
    assert saved_job.is_completed()
    assert saved_job.exit_code == 0

    assert lease_repository.get_by_worker_id(worker.id) is None

    # The actual regression this loop exists to prevent: a completed
    # job must give its allocated resources back to the node, not
    # leak them forever.
    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_run_once_executes_real_successful_command() -> None:
    """
    Proves this is real subprocess execution, not simulated:
    the job's command actually runs, and its real exit code
    flows through to the persisted job.
    """
    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "pass"],
    )

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node)
    )

    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()

    assert saved_job is not None
    assert saved_job.is_completed()
    assert saved_job.exit_code == 0

    assert lease_repository.get_by_worker_id(worker.id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_run_once_marks_job_and_worker_failed_on_nonzero_exit() -> None:
    """
    A command that genuinely fails must result in the job
    being marked FAILED with its real exit code, not
    COMPLETED. This is the path that did not exist at all
    before this loop actually ran real commands.
    """
    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "import sys; sys.exit(7)"],
    )

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node)
    )

    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()

    assert saved_job is not None
    assert saved_job.is_failed()
    assert saved_job.exit_code == 7

    # The lease must still be released even though the job
    # failed -- outcome and lease lifecycle are independent.
    assert lease_repository.get_by_worker_id(worker.id) is None

    # Node resources must be released on failure too -- a failed
    # job is done using the node just as much as a completed one.
    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_run_once_marks_job_failed_when_command_exceeds_timeout() -> None:
    """
    A command that runs past the job's execution_timeout
    must be killed and marked FAILED, with the timeout
    itself enforced by real subprocess termination, not a
    simulated clock.
    """
    from datetime import timedelta

    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "import time; time.sleep(30)"],
    )
    job.execution_timeout = timedelta(seconds=0.5)

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node)
    )

    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()

    assert saved_job is not None
    assert saved_job.is_failed()

    assert lease_repository.get_by_worker_id(worker.id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_run_once_returns_early_when_worker_has_no_running_job() -> None:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    worker.ready()

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository()
    node_repository = InMemoryNodeRepository([node])
    lease_repository = InMemoryLeaseRepository()

    loop = WorkerExecutionLoop(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        renew_lease_service=RenewLeaseService(
            lease_repository=lease_repository,
        ),
        release_lease_service=ReleaseLeaseService(
            lease_repository=lease_repository,
            worker_repository=worker_repository,
        ),
        job_execution_service=JobExecutionService(),
    )

    # Should return without error and without attempting to
    # renew or release a lease that was never acquired.
    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    assert saved_worker is not None
    assert saved_worker.is_idle()
def test_run_once_does_not_restart_a_job_already_running() -> None:
    """
    AssignWorkerService can start a job at assignment time, and
    ClusterTickService drives every worker with a running_job
    through this loop on every subsequent tick. Without a guard,
    a job that's already RUNNING gets a second worker.start() call
    and crashes on InvalidJobTransition, forever, since the crash
    happens before the job can reach a terminal state and clear
    running_job. This proves the loop tolerates a job that's
    already running instead of trying to start it again.
    """
    worker, job, node = _make_worker_and_job()

    # simulate AssignWorkerService having already started the job
    worker.start()

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node)
    )

    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()

    assert saved_job is not None
    assert saved_job.is_completed()
    assert saved_job.exit_code == 0
def test_run_once_records_job_completed_event_on_success() -> None:
    """
    A successful run must record a JobCompleted event.
    """
    worker, job, node = _make_worker_and_job()

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node, record_job_events_service)
    )

    loop.execute(worker.id)

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobCompleted"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_run_once_records_job_failed_event_on_nonzero_exit() -> None:
    """
    A run that exits with a nonzero code must record a
    JobFailed event, not JobCompleted.
    """
    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "import sys; sys.exit(7)"],
    )

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    loop, worker_repository, job_repository, node_repository, lease_repository = (
        _build_loop(worker, job, node, record_job_events_service)
    )

    loop.execute(worker.id)

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobFailed"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_run_once_cancels_job_requested_to_cancel_during_execution() -> None:
    """
    A job whose cancellation is requested (e.g. via
    CancelJobService, a separate request) while it is
    actually running must have its subprocess terminated and
    be persisted as CANCELLED, not left RUNNING or marked
    FAILED (ADR 0029). Cancellation is simulated the same way
    a real concurrent request would apply it: through the job
    repository, not by touching the loop's internals
    directly.
    """
    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "import time; time.sleep(5)"],
    )

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    node_repository = InMemoryNodeRepository([node])

    renew_lease_service = RenewLeaseService(
        lease_repository=lease_repository,
    )

    release_lease_service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    job_execution_service = JobExecutionService(
        poll_interval=timedelta(seconds=0.05),
    )

    loop = WorkerExecutionLoop(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        renew_lease_service=renew_lease_service,
        release_lease_service=release_lease_service,
        job_execution_service=job_execution_service,
        renewal_interval_seconds=0.1,
    )

    def request_cancellation_soon() -> None:
        time.sleep(0.2)
        stored = job_repository.get_by_id(job.id)
        assert stored is not None
        stored.request_cancellation()
        job_repository.save(stored)

    threading.Thread(
        target=request_cancellation_soon,
        daemon=True,
    ).start()

    loop.execute(worker.id)

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()
    assert saved_worker.running_job is None

    assert saved_job is not None
    assert saved_job.is_cancelled()

    assert lease_repository.get_by_worker_id(worker.id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_run_once_records_job_cancelled_event() -> None:
    """
    A confirmed cancellation must record a JobCancelled
    event, distinct from JobCompleted or JobFailed.
    """
    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "import time; time.sleep(5)"],
    )

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    node_repository = InMemoryNodeRepository([node])

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    renew_lease_service = RenewLeaseService(
        lease_repository=lease_repository,
    )

    release_lease_service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    job_execution_service = JobExecutionService(
        poll_interval=timedelta(seconds=0.05),
    )

    loop = WorkerExecutionLoop(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        renew_lease_service=renew_lease_service,
        release_lease_service=release_lease_service,
        job_execution_service=job_execution_service,
        record_job_events_service=record_job_events_service,
        renewal_interval_seconds=0.1,
    )

    def request_cancellation_soon() -> None:
        time.sleep(0.2)
        stored = job_repository.get_by_id(job.id)
        assert stored is not None
        stored.request_cancellation()
        job_repository.save(stored)

    threading.Thread(
        target=request_cancellation_soon,
        daemon=True,
    ).start()

    loop.execute(worker.id)

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobCancelled"
    assert recorded[0].aggregate_id == str(job.id)


def test_run_once_preserves_cancellation_request_lost_by_renewal_thread() -> (
    None
):
    """
    Reproduces a real gap: cancellation delivery relies
    entirely on the renewal thread's periodic check
    (keep_lease_alive), which only runs on each renewal
    timeout. On shutdown, stop_renewing.set() wakes that
    thread immediately without a final check, so if a
    cancellation is persisted to the job repository after
    the renewal thread's last check but before the
    subprocess finishes naturally, the loop's local `job`
    object never learns about it.

    ADR 0029 already establishes that a job completing
    naturally before its kill signal arrives should resolve
    to COMPLETED, not be forced to CANCELLED -- that part is
    correct and not what this test disputes. What this test
    proves is narrower: the audit fact that cancellation was
    ever requested (cancellation_requested_at) must survive
    regardless of which outcome wins, and today it does not
    -- it is silently overwritten by the loop's unconditional
    final job_repository.save(job).

    renewal_interval_seconds is set far longer than the
    command's own runtime so the renewal thread never gets a
    chance to check for the cancellation before the
    subprocess exits on its own.
    """
    worker, job, node = _make_worker_and_job(
        command=["python3", "-c", "import time; time.sleep(0.3)"],
    )

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    node_repository = InMemoryNodeRepository([node])

    renew_lease_service = RenewLeaseService(
        lease_repository=lease_repository,
    )

    release_lease_service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    job_execution_service = JobExecutionService(
        poll_interval=timedelta(seconds=0.05),
    )

    loop = WorkerExecutionLoop(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        renew_lease_service=renew_lease_service,
        release_lease_service=release_lease_service,
        job_execution_service=job_execution_service,
        # Far longer than the command's 0.3s runtime, so the
        # renewal thread's periodic check never actually
        # fires before the subprocess exits on its own.
        renewal_interval_seconds=10.0,
    )

    def request_cancellation_soon() -> None:
        time.sleep(0.1)
        stored = job_repository.get_by_id(job.id)
        assert stored is not None
        stored.request_cancellation()
        job_repository.save(stored)

    threading.Thread(
        target=request_cancellation_soon,
        daemon=True,
    ).start()

    loop.execute(worker.id)

    saved_job = job_repository.get_by_id(job.id)
    assert saved_job is not None

    # The outcome-decision race is intentional per ADR 0029:
    # a job that finishes naturally before its kill signal
    # arrives resolves to COMPLETED, not CANCELLED.
    assert saved_job.is_completed()

    # The audit fact that cancellation was requested must
    # survive regardless of which outcome won. Today it does
    # not: this assertion is expected to fail, demonstrating
    # the gap.
    assert saved_job.cancellation_requested_at is not None


def test_run_once_preserves_cancellation_request_against_sqlite_repository() -> (
    None
):
    """
    Reproduces a real race using a genuinely persistent
    repository, not InMemoryJobRepository, whose get_by_id
    hands back the exact same object reference on every
    call and therefore cannot exhibit this race at all: any
    "concurrent" mutation in a test built on it is actually
    mutating the loop's own in-memory job directly.

    SqliteJobRepository reconstructs a fresh Job from a row
    on every get_by_id call, the same way PostgresJobRepository
    does, so a genuinely separate connection simulating a
    concurrent CancelJobService call is a faithful
    reproduction of two real request-handling threads, each
    with their own repository instance, racing to persist
    the same aggregate.

    Cancellation delivery relies entirely on the renewal
    thread's periodic check (keep_lease_alive), which only
    runs on each renewal timeout. renewal_interval_seconds
    is set far longer than the command's own runtime so that
    check never fires before the subprocess exits on its
    own. On shutdown, stop_renewing.set() wakes the renewal
    thread immediately without a final check.

    ADR 0029 already establishes that a job completing
    naturally before its kill signal arrives should resolve
    to COMPLETED, not be forced to CANCELLED -- that part is
    correct and not disputed here. What this test proves is
    narrower: the audit fact that cancellation was ever
    requested (cancellation_requested_at) must survive
    regardless of which outcome wins. Today it does not: the
    loop's own unconditional final job_repository.save(job)
    overwrites the database row with its stale, never-
    cancelled local copy.
    """
    import os
    import tempfile

    from app.infrastructure.repositories.sqlite_connection import (
        create_connection,
    )
    from app.infrastructure.repositories.sqlite_job_repository import (
        SqliteJobRepository,
    )

    handle, db_path = tempfile.mkstemp(suffix=".db")
    os.close(handle)

    try:
        worker, job, node = _make_worker_and_job(
            command=["python3", "-c", "import time; time.sleep(0.3)"],
        )

        setup_connection = create_connection(db_path)
        setup_repository = SqliteJobRepository(setup_connection)
        setup_repository.save(job)
        setup_connection.close()

        lease = Lease.create(
            worker_id=worker.id,
            job_id=job.id,
        )

        lease_repository = InMemoryLeaseRepository()
        lease_repository.save(lease)

        worker_repository = InMemoryWorkerRepository([worker])
        node_repository = InMemoryNodeRepository([node])

        loop_connection = create_connection(db_path)
        loop_job_repository = SqliteJobRepository(loop_connection)

        renew_lease_service = RenewLeaseService(
            lease_repository=lease_repository,
        )

        release_lease_service = ReleaseLeaseService(
            lease_repository=lease_repository,
            worker_repository=worker_repository,
        )

        job_execution_service = JobExecutionService(
            poll_interval=timedelta(seconds=0.05),
        )

        loop = WorkerExecutionLoop(
            worker_repository=worker_repository,
            job_repository=loop_job_repository,
            node_repository=node_repository,
            renew_lease_service=renew_lease_service,
            release_lease_service=release_lease_service,
            job_execution_service=job_execution_service,
            # Far longer than the command's 0.3s runtime, so
            # the renewal thread's periodic check never
            # actually fires before the subprocess exits on
            # its own.
            renewal_interval_seconds=10.0,
        )

        def request_cancellation_soon() -> None:
            time.sleep(0.1)
            # A genuinely separate connection and repository
            # instance, simulating a real concurrent
            # CancelJobService call, not the loop's own
            # in-memory copy.
            cancel_connection = create_connection(db_path)
            cancel_repository = SqliteJobRepository(
                cancel_connection,
            )
            stored = cancel_repository.get_by_id(job.id)
            assert stored is not None
            stored.request_cancellation()
            cancel_repository.save(stored)
            cancel_connection.close()

        threading.Thread(
            target=request_cancellation_soon,
            daemon=True,
        ).start()

        loop.execute(worker.id)

        loop_connection.close()

        # A third, fresh connection, matching this file's
        # existing round-trip idiom: prove what actually
        # landed in the database, not what any in-process
        # object happens to hold.
        verify_connection = create_connection(db_path)
        verify_repository = SqliteJobRepository(verify_connection)
        saved_job = verify_repository.get_by_id(job.id)
        verify_connection.close()

        assert saved_job is not None

        # The outcome-decision race is intentional per ADR
        # 0029: a job that finishes naturally before its
        # kill signal arrives resolves to COMPLETED, not
        # CANCELLED.
        assert saved_job.is_completed()

        # The audit fact that cancellation was requested
        # must survive regardless of which outcome won.
        assert saved_job.cancellation_requested_at is not None
    finally:
        os.remove(db_path)
