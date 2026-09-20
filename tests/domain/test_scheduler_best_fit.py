from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


def test_scheduler_selects_best_fit_node() -> None:
    """
    Among proportionally-scaled candidates, the smallest node
    that can still fit the job wins. All three resource
    dimensions point to the same answer here, so this alone
    does not prove which dimension(s) the scorer actually
    weighs (see test_scheduler_prefers_tighter_fit_on_vram_not_cpu
    for that).
    """
    scheduler = Scheduler()

    large = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=32,
            memory_mib=65536,
            vram_mib=24576,
        ),
    )

    medium = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    small = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )

    selected = scheduler.select_node(
        job,
        [large, medium, small],
    )

    assert selected == small


def test_scheduler_prefers_tighter_fit_on_vram_not_cpu() -> None:
    """
    ADR 0043: best-fit must weigh VRAM, not just CPU.

    Both nodes can host the job. cpu_heavy has the tighter CPU
    remainder (2 - 1 = 1), so a CPU-only comparison prefers it, but
    it leaves the job's real bottleneck, VRAM, almost entirely
    unused (16384 spare). vram_heavy has a looser CPU remainder
    (3 - 1 = 2) but only 200 MiB of VRAM spare after hosting this
    job -- the genuinely tighter overall fit once VRAM counts.

    A CPU-only formula picks cpu_heavy (smaller CPU remainder). The
    multi-dimensional scorer must pick vram_heavy: its VRAM term
    (200/16384 ~= 0.012) is far smaller than cpu_heavy's
    (16384/16384 = 1.0) and dominates the summed score.
    """
    scheduler = Scheduler()

    cpu_heavy = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )
    # Tight on CPU (2 left), untouched VRAM (16384 left).
    cpu_heavy.allocate(
        ResourceRequirements(
            cpu_cores=14,
            memory_mib=0,
            vram_mib=0,
        ),
    )

    vram_heavy = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )
    # Looser on CPU (3 left), nearly saturated on VRAM (8200 left)
    # -- but still enough to host the job below.
    vram_heavy.allocate(
        ResourceRequirements(
            cpu_cores=13,
            memory_mib=0,
            vram_mib=8184,
        ),
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=8000,
        ),
    )

    selected = scheduler.select_node(
        job,
        [cpu_heavy, vram_heavy],
    )

    assert selected == vram_heavy


def test_scheduler_ignores_unrequested_dimensions_in_scoring() -> None:
    """
    ADR 0043: a job that requests zero VRAM must not have its
    node choice influenced by how much VRAM a candidate has
    free. Two nodes are identical except one has far more spare
    VRAM; a CPU-and-memory-only job must be indifferent between
    them; select_node returns *some* valid candidate, verified
    here as "the VRAM-rich node is not treated as a better fit
    than the identical one with less VRAM," not by asserting a
    specific winner, since a genuine tie is expected.
    """
    scheduler = Scheduler()

    modest_vram = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=1024,
        ),
    )

    huge_vram = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=98304,
        ),
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=0,
        ),
    )

    scores = {
        node.id: scheduler._fit_score(job, node)
        for node in [modest_vram, huge_vram]
    }

    assert scores[modest_vram.id] == scores[huge_vram.id]
