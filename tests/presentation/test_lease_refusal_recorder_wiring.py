"""ADR 0108: the renew and release services share one refusal recorder."""

from __future__ import annotations

from app.application.services.record_lease_refusal_service import (
    RecordLeaseRefusalService,
)
from app.infrastructure.repositories.in_memory_lease_refusal_repository import (
    InMemoryLeaseRefusalRepository,
)
from app.infrastructure.repositories.postgres_lease_refusal_repository import (
    PostgresLeaseRefusalRepository,
)
from app.presentation import dependencies


def test_the_renew_service_is_built_with_the_recorder() -> None:
    service = dependencies._renew_lease_service

    assert isinstance(
        service._record_lease_refusal_service, RecordLeaseRefusalService
    )
    assert (
        service._record_lease_refusal_service
        is dependencies._record_lease_refusal_service
    )


def test_the_release_service_is_built_with_the_recorder() -> None:
    service = dependencies._release_lease_service

    assert isinstance(
        service._record_lease_refusal_service, RecordLeaseRefusalService
    )
    assert (
        service._record_lease_refusal_service
        is dependencies._record_lease_refusal_service
    )


def test_the_outcome_report_releases_through_the_shared_release_service() -> None:
    service = dependencies._report_job_outcome_service

    assert service._release_lease_service is dependencies._release_lease_service


def test_the_recorder_reads_the_reclaim_records_of_the_reclaim_recorder() -> None:
    recorder = dependencies._record_lease_refusal_service

    assert (
        recorder._lease_reclaim_repository
        is dependencies._lease_reclaim_repository
    )


def test_the_recorder_keeps_its_refusals_in_the_store_of_the_backend() -> None:
    repository = dependencies._record_lease_refusal_service._lease_refusal_repository

    if dependencies.get_connection_pool() is not None:
        assert isinstance(repository, PostgresLeaseRefusalRepository)
    else:
        assert isinstance(repository, InMemoryLeaseRefusalRepository)
