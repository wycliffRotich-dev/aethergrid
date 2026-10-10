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
    # Interim: these read a node from a job or worker that carries no
    # tenant, or read a job by an id that arrives without one. Each
    # entry leaves when its caller can pass a tenant.
    "application/services/complete_job_service.py",
    "application/services/fail_job_service.py",
    "application/services/report_job_outcome_service.py",
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
