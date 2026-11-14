from __future__ import annotations

import copy

from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
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
    lease_already_deleted: bool = False,
) -> bool:
    """
    Reclaim a job abandoned by infrastructure failure: delete
    its lease, release its node's allocated resources, and
    transition the job itself via Job.reclaim().

    This exact three-step sequence, in this exact order, has
    now been independently reimplemented by hand three times
    (RecoverExpiredLeaseService, RecoverOfflineNodeService,
    CreateWorkerService) and shipped with a real bug in each
    of those three. The goal of naming it here, the same
    reasoning as persist_job_started above, is that the next
    recovery path this codebase grows does not get a chance to
    rediscover it a fourth time.

    Ordering matters and is deliberately not configurable:

    1. The lease is deleted first, before the job is touched.
       This closes the window where a worker's background
       renewal thread could successfully renew a lease that
       reconciliation has already decided to reclaim -- see
       RecoverExpiredLeaseService's original docstring for the
       full race this prevents.
    2. Job.reclaim() runs next, and the job is saved only if
       reclaim() succeeds. A job that can no longer be reclaimed
       returns False here and is not credited to the node,
       because a job that already finished released its
       capacity when its outcome was reported, and crediting
       it again would make the node report capacity it does
       not have. A CANCELLED job is the exception: cancelling
       a job that has not started never releases its capacity,
       so it is released here, once.
    3. The node's resources are released and the node is saved
       last. The node is passed in already resolved, so
       Job.reclaim() clearing job.assigned_node_id does not
       affect it. A crash between the job save and the node save
       leaves capacity allocated, which under-reports free
       capacity instead of over-reporting it, the safe direction.

    The lease is deleted in the job's tenant. A lease carries the
    tenant of its job (ADR 0075), so no other tenant's lease can
    be touched.

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

    lease_already_deleted: pass True when the caller has
    already deleted the lease itself, conditionally, via
    LeaseRepository.delete_if_expired -- and confirmed it
    actually removed a row. This exists so a caller whose
    reclaim decision depends on the lease still being expired
    at delete time (not just at an earlier snapshot read) can
    perform that fenced check before calling this function,
    rather than this function deleting unconditionally and
    silently reclaiming a job whose lease was legitimately
    renewed in between. See RecoverExpiredLeaseService.
    """
    if not lease_already_deleted:
        lease_repository.delete(
            job.id,
            job.tenant_id,
        )

    try:
        job.reclaim()
    except InvalidJobTransition:
        if job.is_cancelled() and node is not None:
            node.release(
                job.resources,
            )
            node_repository.save(
                node,
            )

        return False

    job_repository.save(
        job,
    )

    if node is not None:
        node.release(
            job.resources,
        )
        node_repository.save(
            node,
        )

    return True


FINISHING_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.RUNNING, JobStatus.CANCELLING}
)
"""
The statuses a job may still have in storage when its outcome is
saved (ADR 0096 decision 10). RUNNING, or CANCELLING when a
cancellation request was saved while it ran, because ADR 0029 lets a
job that finishes before the signal reaches it end COMPLETED or
FAILED. A reclaim moves a job out of both, to QUEUED, FAILED or
CANCELLED, so an outcome saved against this set cannot land on a job
that was reclaimed while the outcome was on its way.
"""


def take_running_job(
    worker: Worker,
) -> Job:
    """
    Give the worker its own copy of its running job, and return it.

    Call it before worker.complete(), worker.fail() or
    worker.cancel_job(), which change the job in place. The in-memory
    job repository hands out the object it stores, so without the copy
    the stored job would show the outcome before it was written, and
    the fenced write that compares against the stored status would
    refuse it. On Postgres the job was read fresh and the copy changes
    nothing.
    """
    if worker.running_job is None:
        raise ValueError(
            "No running job."
        )

    job = copy.deepcopy(worker.running_job)
    worker.running_job = job
    return job


def reclaim_leaseless_job(
    job: Job,
    node: Node | None,
    *,
    node_repository: NodeRepository,
    job_repository: JobRepository,
) -> Job | None:
    """
    Reclaim a job that no lease holds, as one fenced write (ADR 0096).

    The caller's job is never changed. It is copied, the copy is
    reclaimed, and the copy is returned only if its write was
    accepted, so a refused write leaves no object behind that looks
    reclaimed and was never saved. The write is fenced on the status
    the job had when it was handed in, taken from the job itself, so
    a caller cannot pass a status that disagrees with it.

    There is no lease to delete, so none is. The job is saved through
    JobRepository.save_if_leaseless, which applies only while the
    stored job still has that status and no lease row points at it.
    The node is credited only after the write was accepted, and is
    saved after the job (ADR 0092).

    reclaim_job stays the helper for the paths that start from a
    lease. Its result is a bool that its callers rely on, and its job
    is changed in place.

    Returns the reclaimed copy, or None when the job was not in a
    status Job.reclaim() accepts or the write was refused. None means
    nothing was written.
    """
    candidate = copy.deepcopy(job)
    read_status = candidate.status

    try:
        candidate.reclaim()
    except InvalidJobTransition:
        return None

    if not job_repository.save_if_leaseless(
        candidate,
        frozenset({read_status}),
    ):
        return None

    if node is not None:
        node.release(
            candidate.resources,
        )
        node_repository.save(
            node,
        )

    return candidate
