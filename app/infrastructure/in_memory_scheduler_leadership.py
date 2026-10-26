from __future__ import annotations

from app.application.scheduler_leadership import SchedulerLeadership


class InMemorySchedulerLeadership(SchedulerLeadership):
    """
    Leadership for a deployment that has one process (ADR 0078).

    Always leads. It is used by the tests and by local development
    on SQLite, where a second process cannot share the database and
    so there is nothing to elect between.
    """

    def try_acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None
