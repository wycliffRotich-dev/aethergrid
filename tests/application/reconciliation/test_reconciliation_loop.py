from __future__ import annotations

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)


class FakeMarkDeadWorkersService:
    """
    Fake dead worker marking service.
    """

    def __init__(
        self,
    ) -> None:
        self.executed = False

    def execute(
        self,
    ) -> None:
        self.executed = True


class FakeRecoverExpiredLeaseService:
    """
    Fake expired lease recovery service.
    """

    def __init__(
        self,
    ) -> None:
        self.executed = False

    def execute(
        self,
    ) -> None:
        self.executed = True


class FakeRecoverOfflineNodeService:
    """
    Fake offline node recovery service.
    """

    def __init__(
        self,
    ) -> None:
        self.executed = False

    def execute(
        self,
    ) -> None:
        self.executed = True


class FakeRecoverLeaselessJobService:
    """
    Fake leaseless job recovery service.
    """

    def __init__(
        self,
    ) -> None:
        self.executed = False

    def execute(
        self,
    ) -> None:
        self.executed = True


class RaisingService:
    """
    A step that fails every time it runs.
    """

    def execute(
        self,
    ) -> None:
        raise RuntimeError("step failed")


def test_reconciliation_loop_runs_services_in_order() -> None:
    order: list[str] = []

    class Recording:
        def __init__(self, name: str) -> None:
            self._name = name

        def execute(self) -> None:
            order.append(self._name)

    loop = ReconciliationLoop(
        mark_dead_workers_service=Recording("dead"),  # type: ignore[arg-type]
        recover_expired_lease_service=Recording("expired"),  # type: ignore[arg-type]
        recover_offline_node_service=Recording("offline"),  # type: ignore[arg-type]
        recover_leaseless_job_service=Recording("leaseless"),  # type: ignore[arg-type]
    )

    loop.execute()

    assert order == ["dead", "expired", "offline", "leaseless"]


def test_reconciliation_loop_runs_every_service() -> None:
    dead_workers_service = FakeMarkDeadWorkersService()
    expired_service = FakeRecoverExpiredLeaseService()
    offline_service = FakeRecoverOfflineNodeService()
    leaseless_service = FakeRecoverLeaselessJobService()

    loop = ReconciliationLoop(
        mark_dead_workers_service=dead_workers_service,
        recover_expired_lease_service=expired_service,
        recover_offline_node_service=offline_service,
        recover_leaseless_job_service=leaseless_service,
    )

    loop.execute()

    assert dead_workers_service.executed is True
    assert expired_service.executed is True
    assert offline_service.executed is True
    assert leaseless_service.executed is True


def test_a_failing_step_does_not_stop_the_steps_after_it() -> None:
    """
    The leaseless job service repairs what a failed expired-lease
    pass leaves behind, so it must run in the pass that failed.
    """
    offline_service = FakeRecoverOfflineNodeService()
    leaseless_service = FakeRecoverLeaselessJobService()

    loop = ReconciliationLoop(
        mark_dead_workers_service=FakeMarkDeadWorkersService(),
        recover_expired_lease_service=RaisingService(),  # type: ignore[arg-type]
        recover_offline_node_service=offline_service,
        recover_leaseless_job_service=leaseless_service,
    )

    loop.execute()

    assert offline_service.executed is True
    assert leaseless_service.executed is True
