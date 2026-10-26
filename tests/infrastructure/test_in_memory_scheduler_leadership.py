from app.application.scheduler_leadership import SchedulerLeadership
from app.infrastructure.in_memory_scheduler_leadership import (
    InMemorySchedulerLeadership,
)


def test_it_is_a_scheduler_leadership() -> None:
    assert isinstance(InMemorySchedulerLeadership(), SchedulerLeadership)


def test_it_leads_on_every_call() -> None:
    leadership = InMemorySchedulerLeadership()

    assert leadership.try_acquire() is True
    assert leadership.try_acquire() is True


def test_it_leads_again_after_a_release() -> None:
    leadership = InMemorySchedulerLeadership()
    leadership.try_acquire()

    leadership.release()

    assert leadership.try_acquire() is True


def test_release_is_safe_before_any_acquire_and_when_repeated() -> None:
    leadership = InMemorySchedulerLeadership()

    leadership.release()
    leadership.release()
