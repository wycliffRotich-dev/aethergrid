from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.event import Event
from app.domain.entities.job import Job
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.event_id import EventId
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.postgres_event_repository import (
    PostgresEventRepository,
)
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from tests.support.jobs import make_job


class TestPostgresEventRepositoryContract:
    """
    Contract tests for PostgresEventRepository.

    An event belongs to a job and takes the tenant of that job
    (ADR 0074), so every test saves a real job first.
    """

    @pytest.fixture(autouse=True, scope="class")
    @classmethod
    def _pool(cls, test_database_url):
        cls.pool = ConnectionPool(test_database_url, open=True)
        yield
        cls.pool.close()

    def setup_method(
        self,
    ) -> None:
        self.repository = PostgresEventRepository(
            self.pool,
        )
        self.jobs = PostgresJobRepository(
            self.pool,
        )

        with self.pool.connection() as conn:
            conn.execute(
                "TRUNCATE TABLE events, jobs CASCADE",
            )

    def _new_tenant(
        self,
    ) -> TenantId:
        tenant_id = TenantId.new()

        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name, created_at) "
                "VALUES (%s, %s, now())",
                (str(tenant_id), f"t-{uuid.uuid4().hex[:8]}"),
            )

        return tenant_id

    def _job(
        self,
        tenant_id: TenantId = DEFAULT_TENANT_ID,
    ) -> Job:
        job = make_job(
            tenant_id=tenant_id,
        )
        self.jobs.save(
            job,
        )

        return job

    @staticmethod
    def _event(
        job: Job,
        event_type: str = "JobCreated",
    ) -> Event:
        return Event(
            id=EventId.new(),
            aggregate_id=str(job.id),
            aggregate_type="Job",
            event_type=event_type,
            tenant_id=job.tenant_id,
        )

    def test_save_and_list_returns_saved_event(
        self,
    ) -> None:
        event = self._event(self._job())

        self.repository.save(
            event,
        )

        events = self.repository.list()

        assert len(events) == 1
        assert events[0] == event

    def test_list_by_aggregate_returns_only_matching_events(
        self,
    ) -> None:
        job_one = self._job()
        job_two = self._job()
        first = self._event(job_one, "JobCreated")
        second = self._event(job_two, "JobCreated")
        third = self._event(job_one, "JobScheduled")

        self.repository.save(
            first,
        )

        self.repository.save(
            second,
        )

        self.repository.save(
            third,
        )

        events = self.repository.list_by_aggregate(
            str(job_one.id),
        )

        assert len(events) == 2
        assert events[0] == first
        assert events[1] == third

    def test_the_tenant_of_the_job_is_stored_with_the_event(
        self,
    ) -> None:
        tenant_id = self._new_tenant()
        event = self._event(self._job(tenant_id))

        self.repository.save(
            event,
        )

        assert self.repository.list()[0].tenant_id == tenant_id

    def test_a_repeated_id_keeps_the_first_event(
        self,
    ) -> None:
        job = self._job()
        first = self._event(job, "JobCreated")
        again = Event(
            id=first.id,
            aggregate_id=first.aggregate_id,
            aggregate_type="Job",
            event_type="JobFailed",
            tenant_id=first.tenant_id,
        )

        self.repository.save(
            first,
        )

        self.repository.save(
            again,
        )

        events = self.repository.list()

        assert len(events) == 1
        assert events[0].event_type == "JobCreated"

    def test_an_event_in_another_tenants_job_is_refused(
        self,
    ) -> None:
        job = self._job()
        other_tenant = self._new_tenant()
        event = Event(
            id=EventId.new(),
            aggregate_id=str(job.id),
            aggregate_type="Job",
            event_type="JobCreated",
            tenant_id=other_tenant,
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            self.repository.save(
                event,
            )

        assert self.repository.list() == []

    def test_an_event_for_a_missing_job_is_refused(
        self,
    ) -> None:
        never_saved = make_job()

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            self.repository.save(
                self._event(never_saved),
            )

    def test_an_aggregate_id_that_is_not_a_job_is_refused(
        self,
    ) -> None:
        event = Event(
            id=EventId.new(),
            aggregate_id="job-123",
            aggregate_type="Job",
            event_type="JobCreated",
            tenant_id=DEFAULT_TENANT_ID,
        )

        with pytest.raises(psycopg.DataError):
            self.repository.save(
                event,
            )

    def test_an_event_without_a_tenant_is_shown_to_nobody(
        self,
    ) -> None:
        job = self._job()
        event = self._event(job)
        self.repository.save(
            event,
        )

        # What an image from before this change writes: no tenant.
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO events (id, aggregate_id, aggregate_type, "
                "event_type, occurred_at) "
                "VALUES (%s, %s, 'Job', 'JobCreated', now())",
                (str(uuid.uuid4()), str(job.id)),
            )

        assert [e.id for e in self.repository.list()] == [event.id]
        assert [
            e.id for e in self.repository.list_by_aggregate(str(job.id))
        ] == [event.id]
