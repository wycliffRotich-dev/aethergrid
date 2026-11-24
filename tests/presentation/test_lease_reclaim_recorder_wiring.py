"""ADR 0107: the three recovery paths are built with one shared recorder."""

from __future__ import annotations

from app.application.services.record_lease_reclaim_service import (
    RecordLeaseReclaimService,
)
from app.infrastructure.repositories.in_memory_lease_reclaim_repository import (
    InMemoryLeaseReclaimRepository,
)
from app.infrastructure.repositories.postgres_lease_reclaim_repository import (
    PostgresLeaseReclaimRepository,
)
from app.presentation import dependencies


def test_the_expired_lease_path_is_built_with_the_recorder() -> None:
    service = dependencies._recover_expired_lease_service

    assert isinstance(service._record_lease_reclaim_service, RecordLeaseReclaimService)
    assert service._record_lease_reclaim_service is dependencies._record_lease_reclaim_service


def test_the_offline_node_path_is_built_with_the_recorder() -> None:
    service = dependencies._recover_offline_node_service

    assert isinstance(service._record_lease_reclaim_service, RecordLeaseReclaimService)
    assert service._record_lease_reclaim_service is dependencies._record_lease_reclaim_service


def test_worker_registration_is_built_with_the_recorder() -> None:
    service = dependencies.get_create_worker_service()

    assert isinstance(service._record_lease_reclaim_service, RecordLeaseReclaimService)
    assert service._record_lease_reclaim_service is dependencies._record_lease_reclaim_service


def test_the_recorder_keeps_its_records_in_the_store_of_the_backend() -> None:
    repository = dependencies._record_lease_reclaim_service._lease_reclaim_repository

    if dependencies.get_connection_pool() is not None:
        assert isinstance(repository, PostgresLeaseReclaimRepository)
    else:
        assert isinstance(repository, InMemoryLeaseReclaimRepository)
