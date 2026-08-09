# ADR 0019: Standalone Worker Agent Process

## Status

Proposed

## Context

AetherGrid's execution path today has no real distribution in it.
`ClusterTickService` runs inside the API server's own process, on
a one-second `asyncio` background loop (see `app/presentation/api.py`).
Each tick schedules queued jobs onto nodes, assigns idle workers,
and then calls `WorkerExecutionLoop`, which spawns the job's
command as a real subprocess directly on the machine running the
API server, regardless of which `Node` the job was nominally
assigned to.

`Node` is currently a capacity record only. It has no independent
process of its own, no network identity, and no way to actually
receive work. A job "assigned" to a node with 8 GPUs sitting in a
different rack still executes on whatever machine happens to be
running FastAPI.

Separately, `Worker.is_alive()` and `Node.is_alive()` are today
kept true entirely by `useWorkerHeartbeatKeeper.ts`, a React hook
that heartbeats every non-offline worker and node every 20 seconds
for as long as a dashboard tab is open. This is deliberate and
honestly documented (see the hook's own docstring) as a stand-in
for a real agent, not a disguised one; closing the tab correctly
lets liveness lapse within a minute, the same as a real agent
crashing would. But it means the system's liveness guarantee is
currently "someone has a browser tab open," which is not a
guarantee a distributed system can depend on.

Both problems, fake distribution and fake liveness, have the same
root cause: there is no process that actually runs independently
on a node's own behalf. Fixing liveness alone (a standalone
process that only sends heartbeats) would leave the execution
model unchanged and the project's own claim to be "distributed"
still unproven by its own architecture.

## Decision

Introduce a standalone worker agent process (`scripts/run_agent.py`),
one instance per node, responsible for everything a real worker
needs to do on that node's behalf:

- Register itself as a `Worker` against a given `Node` on startup
- Heartbeat its own worker and node on an interval, replacing
  `useWorkerHeartbeatKeeper.ts` entirely once agents are the only
  liveness mechanism
- Poll the API for work assigned to it
- Execute the job's command as a real subprocess, locally, on the
  agent's own machine
- Renew its own lease for the duration of execution
- Report the job's outcome back to the API when finished

The agent communicates with the API exclusively over the existing
authenticated REST surface, the same `Authorization: Bearer`
mechanism the frontend already uses (ADR 0015). No new transport,
no WebSockets, no persistent connections.

Job handoff is pull-based, not push-based. An idle agent polls
"do I have assigned work?" on its own interval, rather than the
server holding an open connection to push work to it. This is a
deliberate choice over push delivery:

- It requires no new failure mode. A crashed or unreachable agent
  is indistinguishable from an agent that simply hasn't polled
  yet, both are correctly handled today by existing dead-worker
  and lease-expiry reconciliation. Push delivery would need its
  own retry and delivery-guarantee logic that doesn't exist
  anywhere else in this codebase.
- It requires no new transport. The project's stack is
  deliberately REST-based end to end; introducing WebSockets or a
  message queue for this one feature would be a heavier
  architectural change than the problem justifies.
- An agent behind NAT or a firewall that only allows outbound
  connections can still participate, since it only ever makes
  outbound calls to the API, never receives inbound ones.

The central server's responsibilities narrow, they do not
disappear. `ClusterTickService` keeps deciding scheduling policy,
which node a job goes to, exactly as `Node.can_host()` and the
domain `Scheduler` already decide it (ADR 0018). What changes is
that assigning a job to a worker no longer means executing it
in-process; it means making that job visible to the correct
agent's next poll.

## Consequences

### Positive

- The system's core claim, distributed job orchestration across
  compute nodes, becomes architecturally true rather than
  simulated by a single process and a browser tab.
- Liveness no longer depends on a dashboard being open. An agent
  is a real, independently running process with its own crash
  and recovery behavior, which reconciliation (ADR 0007, ADR
  0011) already knows how to handle correctly.
- No new failure modes are introduced. Polling reuses the exact
  liveness and reconciliation model this project already has
  proven correct under concurrent failure.
- `useWorkerHeartbeatKeeper.ts` and its explicit "this is a
  stand-in" docstring can be deleted once agents exist, removing
  the one piece of this codebase that was honestly documented as
  temporary.

### Negative

- This changes the core execution path, not an additive feature.
  It cannot land as a single commit without real risk to what
  currently works.
- Polling has inherent latency, bounded by the agent's poll
  interval, between a job being assigned and an agent picking it
  up. This is an accepted tradeoff for the simplicity and safety
  described above, not an oversight.
- Local development now requires running at least one agent
  process alongside the API and frontend for jobs to actually
  execute, one more moving part than today's single `docker
  compose up`.

## Alternatives Considered

### Push-based job delivery (server calls the agent directly)

Rejected.

Would require the server to hold a persistent connection or
maintain the agent's network address, and would need its own
retry and delivery-guarantee logic for the case where an agent is
temporarily unreachable, logic this codebase does not otherwise
have and that duplicates what reconciliation already does for the
polling model. Also incompatible with agents running behind NAT
or a firewall that only permits outbound connections.

### Message queue between server and agents (e.g. Redis, RabbitMQ)

Rejected.

Introduces a new infrastructure dependency and a new persistence
concern for a project whose stated architecture is deliberately
REST-based end to end (see project stack). The polling model
achieves the same job-handoff guarantee using infrastructure that
already exists.

### Fix liveness only, leave execution centralized

Rejected.

Would resolve the dashboard-tab dependency but leave the
project's own "distributed" claim unproven by its actual
execution path; a job would still run wherever the API server
happens to be, not on the node it was assigned to. Judged a
partial fix to a problem that has one root cause, not two.
