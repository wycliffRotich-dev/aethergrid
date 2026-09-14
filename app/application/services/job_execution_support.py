from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.exceptions.invalid_job_transition import (
    InvalidJobTransition,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)


def persist_job_started(
    job_repository: JobRepository,
    worker: Worker,
) -> None:
    """
    Persist the job a worker just started, immediately.

    worker.start() mutates worker.running_job to RUNNING in
    memory, but WorkerRepository.save() only ever writes the
    workers table, never the job itself. Any caller that
    transitions a worker to RUNNING must call this right
    after, or the jobs table row stays SCHEDULED for the
    job's entire real execution (ADR 0033). This has already
    been independently rediscovered once; the goal of naming
    it here is that the next code path that starts a worker
    does not have to rediscover it a third time.
    """
    if worker.running_job is not None:
        job_repository.save(worker.running_job)


def reclaim_job(
    job: Job,
    node: Node | None,
    *,
    lease_repository: LeaseRepository,
    node_repository: NodeRepository,
    job_repository: JobRepository,
) -> bool:
    """
    Reclaim a job abandoned by infrastructure failure: delete
    its lease, release its node's allocated resources, and
    transition the job itself via Job.reclaim().

    This exact three-step sequence, in this exact order, has
    now been independently reimplemented by hand three times
    (RecoverExpiredLeaseService, RecoverOfflineNodeService,
    CreateWorkerService) and shipped with a real bug in each
    of those three, plus two further dead-but-tested services
    (CompleteJobService, FailJobService) that share the same
    shape. The goal of naming it here, the same reasoning as
    persist_job_started above, is that the next recovery path
    this codebase grows does not get a chance to rediscover
    it a fourth time.

    Ordering matters and is deliberately not configurable:

    1. The lease is deleted first, before the job is touched.
       This closes the window where a worker's background
       renewal thread could successfully renew a lease that
       reconciliation has already decided to reclaim -- see
       RecoverExpiredLeaseService's original docstring for the
       full race this prevents.
    2. The node's resources are released and the node is saved
       next, while job.assigned_node_id (which Job.reclaim()
       is about to clear) still points at the right node.
    3. Job.reclaim() runs last, and its own job_repository.save()
       only happens if reclaim() succeeds.

    node is passed in already resolved, not looked up here,
    since how to find it genuinely differs per caller: some
    already hold it (Worker.node), others must look it up via
    job.assigned_node_id. Pass None if there is nothing to
    release, or if the caller has already determined the node
    no longer exists; this function will simply skip that step.

    Returns True if the job was successfully reclaimed, False
    if the job was no longer in a reclaimable state
    (Job.reclaim() raised InvalidJobTransition). The lease is
    already deleted either way; a False return means there is
    nothing further for the caller to persist for this job,
    not that anything failed. Callers that want to log or
    record an event only on success should check the return
    value.

    Does not touch the worker or record any event; both
    remain the caller's responsibility, since what "recovering
    the worker" or "which event to record" means differs by
    caller (for example, RecoverExpiredLeaseService records
    JobCancelled instead of JobReclaimed for a job that was
    already CANCELLING).
    """
    lease_repository.delete(
        job.id,
    )

    if node is not None:
        node.release(
            job.resources,
        )
        node_repository.save(
            node,
        )

    try:
        job.reclaim()
    except InvalidJobTransition:
        return False

    job_repository.save(
        job,
    )

    return True
