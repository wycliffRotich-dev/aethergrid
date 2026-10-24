from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

# ADR 0064, point 4: a method named *_across_tenants acts on the whole
# fleet, so who may call one is decided here, in one visible place.
# A new caller fails this test until it is added with a reason, and each
# caller is pinned to the exact calls it makes, by method, so a new
# unscoped read inside an allowed file fails too. Calls are counted from
# the parsed source, so a comment or a docstring that names a method does
# not count. A call made through getattr or a stored reference would not
# be seen.
APP = Path(__file__).resolve().parents[2] / "app"
SUFFIX = "_across_tenants"

EXPECTED_CALLS = {
    # The credential lookup cannot know the tenant in advance.
    "application/services/authenticate_api_key_service.py": {
        "get_by_hash_across_tenants": 1,
    },
    # System actors that act on the whole fleet by design.
    "application/services/scheduler_loop_service.py": {
        "list_across_tenants": 1,
        "list_available_across_tenants": 1,
    },
    "application/reconciliation/recover_offline_node_service.py": {
        "delete_if_expired_across_tenants": 1,
        "list_across_tenants": 2,
    },
    "application/reconciliation/recover_expired_lease_service.py": {
        "delete_if_expired_across_tenants": 1,
        "get_by_id_across_tenants": 2,
        "list_across_tenants": 1,
    },
    # Fleet-wide sweeps with no caller tenant: the cluster tick and
    # the dead-worker sweep visit every worker (ADR 0075 decision 10).
    "application/services/cluster_tick_service.py": {
        "list_across_tenants": 1,
    },
    "application/services/mark_dead_workers_service.py": {
        "list_across_tenants": 1,
    },
    # Called by the scheduler loop, which has no caller tenant. The scan
    # must see a worker of another tenant, so that a lease refused for
    # a tenant mismatch is logged as the bug it is (ADR 0075 decision
    # 14). AcquireLeaseService refuses the cross-tenant lease.
    "application/services/assign_worker_service.py": {
        "list_across_tenants": 1,
    },
    # The loop is handed a worker id and nothing else, so it cannot
    # know the tenant before it loads the worker. That one read stays
    # across tenants. Every later read uses the worker's tenant, and
    # test_worker_execution_loop.py pins that (ADR 0075 decision 10).
    "application/workers/worker_execution_loop.py": {
        "get_by_id_across_tenants": 1,
    },
}


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return name if name and name.endswith(SUFFIX) else None


def _calls_by_file(root: str) -> dict[str, dict[str, int]]:
    found: dict[str, dict[str, int]] = {}
    for path in (APP / root).rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        names = [
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            if (name := _called_name(node))
        ]
        if names:
            found[path.relative_to(APP).as_posix()] = dict(Counter(names))
    return found


def test_only_known_callers_use_across_tenants_reads() -> None:
    callers = set(_calls_by_file("application"))
    allowed = set(EXPECTED_CALLS)

    assert callers == allowed, (
        f"unexpected callers: {sorted(callers - allowed)}; "
        f"allowlisted but no longer calling: {sorted(allowed - callers)}"
    )


def test_each_caller_makes_exactly_the_calls_it_is_allowed() -> None:
    found = _calls_by_file("application")
    problems = []
    for file, expected in EXPECTED_CALLS.items():
        actual = found.get(file, {})
        for method in sorted(set(expected) | set(actual)):
            if expected.get(method, 0) != actual.get(method, 0):
                problems.append(
                    f"{file}: {method} expected {expected.get(method, 0)}, "
                    f"found {actual.get(method, 0)}"
                )

    assert not problems, (
        "; ".join(problems)
        + ". A new or removed across-tenants call needs a reason here "
        "(ADR 0064, point 4)."
    )


def test_routes_never_use_across_tenants_reads() -> None:
    assert _calls_by_file("presentation") == {}
