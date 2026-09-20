from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.entities.node import Node


class Scheduler:
    """
    Domain service responsible for selecting the most
    appropriate node for a job.
    """

    def _matches_constraints(
        self,
        job: Job,
        node: Node,
    ) -> bool:
        """
        Return True if the node satisfies all job
        scheduling constraints.

        Jobs with no constraints (the default, empty
        dict) are compatible with every node.
        """
        for key, value in job.constraints.items():
            if node.labels.get(key) != value:
                return False

        return True

    def _fit_score(
        self,
        job: Job,
        node: Node,
    ) -> float:
        """
        Score how tightly a node fits a job's resource
        requirements, lower is a tighter fit (ADR 0043).

        Sums normalized tightness, (available minus
        requested) divided by total capacity, across
        only the dimensions the job actually requests a
        nonzero amount of. Normalizing by each node's own
        capacity keeps CPU, memory, and VRAM on comparable
        footing rather than letting whichever dimension
        has the largest raw numbers (typically memory,
        measured in MiB) dominate the score by unit scale
        alone. Excluding zero-requested dimensions means a
        job that requests no VRAM is never steered toward
        or away from a node based on VRAM it will never
        touch.
        """
        score = 0.0

        if job.resources.cpu_cores > 0:
            score += (
                node.available.cpu_cores - job.resources.cpu_cores
            ) / node.capacity.cpu_cores

        if job.resources.memory_mib > 0:
            score += (
                node.available.memory_mib - job.resources.memory_mib
            ) / node.capacity.memory_mib

        if job.resources.vram_mib > 0:
            score += (
                node.available.vram_mib - job.resources.vram_mib
            ) / node.capacity.vram_mib

        return score

    def select_node(
        self,
        job: Job,
        nodes: list[Node],
    ) -> Node | None:
        """
        Select the best-fit node capable of hosting
        the given job.

        A node must:
        - be alive
        - not be draining
        - satisfy all job constraints
        - have sufficient available resources

        Among all valid candidates, choose the node with
        the lowest normalized fit score across every
        resource dimension the job actually requests
        (ADR 0043), not CPU alone.
        """
        candidates = [
            node
            for node in nodes
            if (
                node.is_alive()
                and not node.is_draining()
                and self._matches_constraints(
                    job,
                    node,
                )
                and node.can_host(
                    job.resources,
                )
            )
        ]

        if not candidates:
            return None

        return min(
            candidates,
            key=lambda node: self._fit_score(job, node),
        )
