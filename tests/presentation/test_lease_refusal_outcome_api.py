"""ADR 0108: a refused outcome report is recorded as a refused release."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.presentation import dependencies
from app.presentation.api import app
from tests.support.jobs import make_job


def test_a_stale_outcome_report_is_refused_with_409_and_recorded_as_a_release() -> None:
    with TestClient(app) as client:
        node_id = client.post(
            "/nodes",
            json={"cpu_cores": 8, "memory_mib": 16384, "vram_mib": 8192},
        ).json()["id"]
        worker_id = client.post(
            "/workers",
            json={"node_id": node_id},
        ).json()["id"]

        job = make_job(
            id=JobId.new(),
            resources=ResourceRequirements(cpu_cores=2, memory_mib=2048),
        )
        job.queue()
        job.assign_to(NodeId(node_id))
        dependencies._job_repository.save(job)

        worker = dependencies._worker_repository.get_by_id_across_tenants(
            WorkerId(worker_id)
        )
        assert worker is not None

        worker.accept(job)
        worker.start()
        dependencies._job_repository.save(job)
        dependencies._worker_repository.save(worker)

        lease = AcquireLeaseService(
            lease_repository=dependencies._lease_repository,
        ).execute(worker, job)

        dependencies._record_lease_reclaim_service.record(
            lease,
            LeaseRecoveryPath.EXPIRED_LEASE,
        )
        dependencies._lease_repository.delete(job.id, worker.tenant_id)

        response = client.post(
            f"/workers/{worker_id}/jobs/{job.id}/complete",
            json={"lease_id": str(lease.id)},
        )

        assert response.status_code == 409
        assert response.json() == {
            "detail": str(NoActiveLeaseError(WorkerId(worker_id)))
        }

        refusals = dependencies._lease_refusal_repository.list_for_lease(
            lease.id,
            worker.tenant_id,
        )

        assert len(refusals) == 1
        assert refusals[0].operation is LeaseRefusalOperation.RELEASE
        assert refusals[0].reason is LeaseRefusalReason.NO_ACTIVE_LEASE
        assert refusals[0].worker_id == WorkerId(worker_id)
        assert refusals[0].job_id == job.id
