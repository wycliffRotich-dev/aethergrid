from __future__ import annotations

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
    fence_status: JobStatus | None = None,
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

    fence_status: pass the status the caller read when the job is
    reclaimed because no lease holds it at all (ADR 0096). There is
    no lease to delete then, so none is, and lease_already_deleted
    keeps the meaning ADR 0052 gives it: a fenced delete that
    removed a row. The job is saved through
    JobRepository.save_if_leaseless instead of save(), so the write
    applies only while the job still has that status and no lease
    row exists. A refused write returns False and credits no node.
    The job object was changed by Job.reclaim() before the write,
    so a caller that passes fence_status must hand in a copy it does
    not reuse.
    """
    if fence_status is None and not lease_already_deleted:
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

    if fence_status is None:
        job_repository.save(
            job,
        )
    elif not job_repository.save_if_leaseless(
        job,
        fence_status,
    ):
        return False

    if node is not None:
        node.release(
            job.resources,
        )
        node_repository.save(
            node,
        )

    return True
