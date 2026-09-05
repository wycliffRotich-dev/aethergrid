from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.repositories.job_repository import JobRepository


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
