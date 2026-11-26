"""ADR 0108: a refused renew through the API leaves one record."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease_refusal import LeaseRefusal
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
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_lease_refusal_repository import (
    InMemoryLeaseRefusalRepository,
)
from app.presentation import dependencies
from app.presentation.api import app
from tests.support.jobs import make_job


class _FailingRefusals(InMemoryLeaseRefusalRepository):
    def save(self, refusal: LeaseRefusal) -> None:
        raise RuntimeError("database down")


def _worker_without_a_lease(client: TestClient) -> str:
    node_id = client.post(
        "/nodes",
        json={"cpu_cores": 8, "memory_mib": 16384, "vram_mib": 8192},
    ).json()["id"]

    return client.post("/workers", json={"node_id": node_id}).json()["id"]


def _reclaimed_lease(
    client: TestClient,
) -> tuple[str, TenantId, Job, UUID]:
    """
    A worker that held a lease which reclaim then removed, with the
    reclaim record kept, as the recovery paths leave it.
    """
    node_id = client.post(
        "/nodes",
        json={"cpu_cores": 8, "memory_mib": 16384, "vram_mib": 8192},
    ).json()["id"]
    worker_id = client.post("/workers", json={"node_id": node_id}).json()["id"]

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
    dependencies._worker_repository.save(worker)

    lease = AcquireLeaseService(
        lease_repository=dependencies._lease_repository,
    ).execute(worker, job)

    dependencies._record_lease_reclaim_service.record(
        lease,
        LeaseRecoveryPath.EXPIRED_LEASE,
    )
    dependencies._lease_repository.delete(job.id, worker.tenant_id)

    return worker_id, worker.tenant_id, job, lease.id


def _expected_detail(worker_id: str) -> str:
    return str(NoActiveLeaseError(WorkerId(worker_id)))


def test_a_stale_renew_is_refused_with_409_and_recorded_once() -> None:
    with TestClient(app) as client:
        worker_id, tenant_id, job, lease_id = _reclaimed_lease(client)

        response = client.post(
            f"/workers/{worker_id}/lease/renew",
            json={"lease_id": str(lease_id)},
        )

        assert response.status_code == 409
        assert response.json() == {"detail": _expected_detail(worker_id)}

        refusals = dependencies._lease_refusal_repository.list_for_lease(
            lease_id,
            tenant_id,
        )

        assert len(refusals) == 1
        assert refusals[0].operation is LeaseRefusalOperation.RENEW
        assert refusals[0].reason is LeaseRefusalReason.NO_ACTIVE_LEASE
        assert refusals[0].worker_id == WorkerId(worker_id)
        assert refusals[0].job_id == job.id
        assert refusals[0].tenant_id == tenant_id


def test_a_failed_refusal_write_does_not_change_the_409(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with TestClient(app) as client:
        worker_id, tenant_id, _job, lease_id = _reclaimed_lease(client)

        monkeypatch.setattr(
            dependencies._record_lease_refusal_service,
            "_lease_refusal_repository",
            _FailingRefusals(),
        )

        with caplog.at_level(logging.DEBUG):
            response = client.post(
                f"/workers/{worker_id}/lease/renew",
                json={"lease_id": str(lease_id)},
            )

        assert response.status_code == 409
        assert response.json() == {"detail": _expected_detail(worker_id)}

        loud = [
            r
            for r in caplog.records
            if r.name == "app.application.services.record_lease_refusal_service"
            and r.levelno >= logging.WARNING
        ]

        assert len(loud) == 1
        assert str(lease_id) in loud[0].getMessage()

    assert (
        dependencies._lease_refusal_repository.list_for_lease(
            lease_id,
            tenant_id,
        )
        == []
    )


def test_a_lease_nobody_held_is_refused_and_not_recorded() -> None:
    with TestClient(app) as client:
        worker_id = _worker_without_a_lease(client)
        made_up = uuid4()

        response = client.post(
            f"/workers/{worker_id}/lease/renew",
            json={"lease_id": str(made_up)},
        )

        assert response.status_code == 409
        assert response.json() == {"detail": _expected_detail(worker_id)}

        worker = dependencies._worker_repository.get_by_id_across_tenants(
            WorkerId(worker_id)
        )
        assert worker is not None

        assert (
            dependencies._lease_refusal_repository.list_for_lease(
                made_up,
                worker.tenant_id,
            )
            == []
        )
