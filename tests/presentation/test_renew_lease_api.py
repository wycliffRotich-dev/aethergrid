from fastapi.testclient import TestClient

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.domain.entities.job import Job
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.presentation.api import app


def test_renew_lease_succeeds_while_worker_holds_a_job() -> None:
    """
    Renewing the lease a worker actually holds must return 200
    and extend its expiry, without changing the worker's status
    or the job it's holding.

    Jobs created through the public API have no command, so
    JobExecutionService completes them synchronously within the
    same tick they're assigned, leaving no stable window to
    renew a lease against (see ADR 0019). To exercise this
    endpoint against a genuinely held lease without waiting on
    real out-of-process execution, this test bypasses POST
    /jobs and constructs the held-lease state directly through
    the domain and repository layer, the same real objects and
    transitions the system uses internally, just without the
    synchronous completion that only happens when a job has a
    command.
    """
    from app.presentation.dependencies import (
        _job_repository,
        _lease_repository,
        _worker_repository,
    )

    with TestClient(app) as client:
        node_response = client.post(
            "/nodes",
            json={
                "cpu_cores": 8,
                "memory_mib": 16384,
                "vram_mib": 8192,
            },
        )
        node_id = node_response.json()["id"]

        worker_response = client.post(
            "/workers",
            json={"node_id": node_id},
        )
        worker_id = worker_response.json()["id"]

        job = Job(
            id=JobId.new(),
            resources=ResourceRequirements(
                cpu_cores=2,
                memory_mib=2048,
            ),
        )
        job.queue()
        job.assign_to(NodeId(node_id))
        _job_repository.save(job)

        worker = _worker_repository.get_by_id(
            WorkerId(worker_id),
        )
        assert worker is not None

        worker.accept(job)
        _worker_repository.save(worker)

        lease = AcquireLeaseService(
            lease_repository=_lease_repository,
        ).execute(worker, job)

        original_expiry = lease.expires_at

        response = client.post(
            f"/workers/{worker_id}/lease/renew",
        )

        assert response.status_code == 200

        renewed_lease = _lease_repository.get_by_worker_id(
            WorkerId(worker_id),
        )
        assert renewed_lease is not None
        assert renewed_lease.expires_at > original_expiry

        body = response.json()
        assert body["status"] == "BUSY"
        assert body["running_job"]["id"] == str(job.id)


def test_renew_lease_with_no_active_lease_returns_409() -> None:
    """
    A worker that exists but holds no lease, whether it never
    acquired one or already released it, must return 409, not
    404 -- the worker itself is real, only the lease is missing.
    """
    with TestClient(app) as client:
        node_response = client.post(
            "/nodes",
            json={
                "cpu_cores": 8,
                "memory_mib": 16384,
                "vram_mib": 8192,
            },
        )
        node_id = node_response.json()["id"]

        worker_response = client.post(
            "/workers",
            json={"node_id": node_id},
        )
        worker_id = worker_response.json()["id"]

        response = client.post(
            f"/workers/{worker_id}/lease/renew",
        )
        assert response.status_code == 409


def test_renew_lease_with_nonexistent_worker_returns_404() -> None:
    with TestClient(app) as client:
        fake_worker_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/workers/{fake_worker_id}/lease/renew",
        )
        assert response.status_code == 404


def test_renew_lease_with_malformed_worker_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/not-a-valid-id/lease/renew",
        )
        assert response.status_code == 422
