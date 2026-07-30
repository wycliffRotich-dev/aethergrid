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


def test_reconciliation_loop_runs_services_in_order() -> None:
    dead_workers_service = FakeMarkDeadWorkersService()
    expired_service = FakeRecoverExpiredLeaseService()
    offline_service = FakeRecoverOfflineNodeService()

    loop = ReconciliationLoop(
        mark_dead_workers_service=dead_workers_service,
        recover_expired_lease_service=expired_service,
        recover_offline_node_service=offline_service,
    )

    loop.execute()

    assert dead_workers_service.executed is True
    assert expired_service.executed is True
    assert offline_service.executed is True
