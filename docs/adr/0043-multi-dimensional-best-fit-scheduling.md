# ADR 0043: Multi-Dimensional Best-Fit Scheduling, Not CPU-Only

## Status

Accepted

## Context

Scheduler.select_node() chose among eligible nodes using a single
comparison: node.available.cpu_cores minus job.resources.cpu_cores,
picking the smallest remainder. This measures fit on CPU alone.
Memory and VRAM played no role in which node was selected once a
node passed the can_host() sufficiency check. For a system explicitly
built around AI workloads, where VRAM and memory are frequently the
binding constraint, not CPU, this is the wrong dimension to optimize
in isolation. A node could be selected as the "best fit" while
leaving a worse fragmentation footprint on the cluster's actual
bottleneck resource for AI jobs.

This was untested as a deliberate design choice, not merely
unexercised. test_scheduler_best_fit.py's three candidate nodes scale
CPU, memory, and VRAM proportionally together, so the existing test
cannot distinguish "best-fit optimizes CPU" from "best-fit optimizes
memory" from "best-fit optimizes VRAM": all three interpretations
would pick the same node against that fixture. No test exists where a
node is tightest on CPU while wasteful on memory, or the reverse.
Nothing evidenced that CPU-only was chosen for a reason, as opposed to
simply being the first dimension implemented and never revisited
since PR #93.

## Decision

select_node() now scores each candidate node by summing normalized
tightness across every resource dimension the job actually requests.
For each dimension the job requests a nonzero amount of, the term
added to the node's score is: (node.available in that dimension minus
job.resources in that dimension), divided by the node's total
capacity in that dimension. The lowest total score wins.

Two properties are deliberate, not incidental:

- Normalization by each node's own capacity, not a raw sum across
  dimensions. Summing raw remaining CPU cores and raw remaining MiB
  of memory would let memory dominate the score purely from unit
  scale, since a difference of a few thousand MiB dwarfs a difference
  of a few CPU cores, producing a score that looks multi-dimensional
  but is functionally still memory-only. Normalizing each term to a
  fraction of that node's total capacity in that dimension puts CPU,
  memory, and VRAM on comparable footing before they are summed.
- Scoring only dimensions the job actually requests, meaning a
  nonzero requirement. A job with vram_mib equal to zero should not
  have its node choice influenced by how much VRAM a candidate node
  has free, since that dimension is irrelevant to a job that never
  touches VRAM, and including it would let VRAM availability sway
  placement of jobs that do not need any.

This generalizes the previous behavior rather than replacing it
outright: a job that only meaningfully requests CPU reduces to the
same CPU-only comparison that existed before.

## Consequences

Best-fit selection now considers the actual resource shape of each
job, not only its CPU footprint. A GPU-heavy job with modest CPU
needs is placed based on how tightly it fits a candidate's available
VRAM, not how tightly it fits available CPU cores it barely uses.

test_scheduler_best_fit.py's existing fixture, with proportional
nodes, no longer meaningfully distinguishes the old behavior from the
new one on its own. A new test with nodes deliberately tight on
different individual dimensions is required to prove the
multi-dimensional scoring actually drives selection, not just that
some node gets picked. Job-stub test helpers that duck-type only a
resources attribute are replaced with real Job entities wherever this
scheduler is exercised, so Scheduler._matches_constraints no longer
needs a defensive getattr for an attribute that Job always actually
has.

This does not change can_host()'s sufficiency check. A node must
still have enough of every resource to run the job at all; this ADR
only changes how ties among sufficient candidates are broken.
