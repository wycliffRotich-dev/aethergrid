from __future__ import annotations

import re
from pathlib import Path

# ADR 0064, point 4: a method named *_across_tenants acts on the whole
# fleet, so who may call one is decided here, in one visible place.
# A new caller fails this test until it is added with a reason.
# The match is by file, so it does not tell a node read from a job read.
APP = Path(__file__).resolve().parents[2] / "app"
ACROSS_TENANTS_CALL = re.compile(r"(?<!def )\b\w+_across_tenants\(")

ALLOWED_CALLERS = {
    # The credential lookup cannot know the tenant in advance.
    "application/services/authenticate_api_key_service.py",
    # System actors that act on the whole fleet by design.
    "application/services/scheduler_loop_service.py",
    "application/reconciliation/recover_offline_node_service.py",
    "application/reconciliation/recover_expired_lease_service.py",
    # Fleet-wide sweeps with no caller tenant: the cluster tick and
    # the dead-worker sweep visit every worker (ADR 0075 decision 10).
    "application/services/cluster_tick_service.py",
    "application/services/mark_dead_workers_service.py",
    # Called by the scheduler loop, which has no caller tenant. The scan
    # must see a worker of another tenant, so that a lease refused for
    # a tenant mismatch is logged as the bug it is (ADR 0075 decision
    # 14). AcquireLeaseService refuses the cross-tenant lease.
    "application/services/assign_worker_service.py",
    # The loop is handed a worker id and nothing else, so it cannot
    # know the tenant before it loads the worker. That one read stays
    # across tenants. Every later read uses the worker's tenant, and
    # test_worker_execution_loop.py pins that (ADR 0075 decision 10).
    "application/workers/worker_execution_loop.py",
}


def _files_calling_across_tenants(*roots: str) -> set[str]:
    found = set()
    for root in roots:
        for path in (APP / root).rglob("*.py"):
            if ACROSS_TENANTS_CALL.search(path.read_text()):
                found.add(path.relative_to(APP).as_posix())
    return found


def test_only_known_callers_use_across_tenants_reads() -> None:
    callers = _files_calling_across_tenants("application")

    assert callers == ALLOWED_CALLERS, (
        f"unexpected callers: {sorted(callers - ALLOWED_CALLERS)}; "
        f"allowlisted but no longer calling: "
        f"{sorted(ALLOWED_CALLERS - callers)}"
    )


def test_routes_never_use_across_tenants_reads() -> None:
    assert _files_calling_across_tenants("presentation") == set()
