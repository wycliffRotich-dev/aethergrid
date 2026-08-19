<p align="center">
  <img src="docs/assets/aethergrid-logo.png" alt="AetherGrid" width="140"/>
</p>

<h1 align="center">AetherGrid</h1>

<p align="center">
  <b>An enterprise control plane for distributed AI workload orchestration.</b><br/>
  I built it around the problems that make scheduling hard at scale: exclusive execution ownership under failure,
  reconciliation after partial failures, and enforced resource limits.
</p>

<p align="center">
  <a href="https://aethergrid-dashboard.onrender.com"><b>Live Console</b></a> ·
  <a href="/docs/adr"><b>Architecture Decision Records</b></a>
</p>

<p align="center">
  <img alt="Tests" src="https://img.shields.io/badge/tests-280%20passing-brightgreen"/>
  <img alt="ADRs" src="https://img.shields.io/badge/ADRs-24-blue"/>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-lightgrey"/>
  <img alt="Python" src="https://img.shields.io/badge/backend-Python%20%2F%20FastAPI-informational"/>
  <img alt="React" src="https://img.shields.io/badge/frontend-React%2019%20%2F%20TypeScript-informational"/>
  <img alt="Postgres" src="https://img.shields.io/badge/database-PostgreSQL-336791"/>
  <img alt="Docker" src="https://img.shields.io/badge/containerized-Docker-2496ED"/>
</p>

---

## What This Is

AetherGrid takes AI workloads, matches them against available compute nodes based on resource requirements and
constraints, and manages their full lifecycle: queued, scheduled, running, completed, failed, retried, cancelled.
Jobs run through workers registered against nodes, and I enforce job execution ownership through time bound
leases, not a simple assignment flag. Every route in the system requires API key authentication, including the
endpoint that issues keys.

This is not a scheduler side project wrapped around an in-memory dictionary. It is a demonstration of the
architecture I believe separates systems that stay correct as they grow from systems that do not: a pure domain
layer with zero infrastructure dependencies, lease based ownership instead of assignment flags, reconciliation
that repairs the failure modes the happy path cannot catch, and every non-obvious decision recorded as an ADR at
the moment I made it, not reconstructed afterward for a portfolio.

## Why I Built It This Way

Most scheduler side projects work fine right up until you need to swap the persistence engine, add a new
constraint type, or figure out why a job silently disappeared, or why two workers picked up the same job at once.

I built AetherGrid around one rule: **the domain logic does not know or care where the data lives.** Jobs, nodes,
workers, and the allocation algorithm are pure Python with zero infrastructure dependencies. The database is a
detail, not the foundation. This project is my concrete proof that these architectural patterns are not
conference talk vocabulary. They are the guardrails that keep a codebase understandable as its correctness
requirements get harder.

## Engineering Decision Records

Every non-obvious decision in this codebase, why a domain rule lives where it does, why an obvious looking
shortcut got rejected, what broke and how I fixed it, is written down at the moment I made the call, not
reconstructed later. 24 ADRs live in [`/docs/adr`](/docs/adr). A few worth reading directly if you want to see the
reasoning, not just the conclusion:

| ADR | Decision |
|---|---|
| [0007](/docs/adr/0007-reconciliation-loop.md) | Reconciliation Loop. How the system detects and repairs state left inconsistent by dead workers and expired leases, instead of assuming the happy path is the only path. |
| [0011](/docs/adr/0011-job-reclaim-and-reconciliation-repair.md) | Job Reclaim and Reconciliation Repair. Closing a race condition where a dying worker's lease renewal could land after reconciliation had already started reassigning its work. |
| [0012](/docs/adr/0012-real-job-execution.md) | Real Job Execution. Building genuine subprocess execution with enforced timeouts, then deliberately keeping it unreachable from the public API until the system had authentication, and proving that absence with a test rather than a comment. |
| [0014](/docs/adr/0014-continuous-lease-renewal.md) | Continuous Lease Renewal. Why a lease gets renewed continuously for a job's entire runtime instead of once at acquisition. |
| [0015](/docs/adr/0015-api-key-authentication.md) | API Key Authentication. Why I chose opaque server issued tokens over JWTs for a system that needs instant revocation. |
| [0018](/docs/adr/0018-domain-owns-scheduling-policy.md) | Domain Owns Scheduling Policy. Why `list_available()` moved out of the repository entirely, since eligibility for scheduling is a business rule, not a persistence concern. |
| [0019](/docs/adr/0019-standalone-worker-agent-process.md) | Standalone Worker Agent Process. Replacing in-process job execution with a real out-of-process agent, and why I chose pull based polling over push delivery. |
| [0020](/docs/adr/0020-expose-job-command-to-authenticated-agents.md) | Expose Job Command to Authenticated Agents. Narrowly reopening command exposure so a worker can read the one command already assigned to it, nothing broader. |
| [0021](/docs/adr/0021-per-api-key-rate-limiting.md) | Per-API-Key Rate Limiting. How the public API is protected from abuse without punishing legitimate burst traffic from a single caller. |
| [0022](/docs/adr/0022-structured-request-and-background-loop-logging.md) | Structured Request and Background Loop Logging. Why every request and every background loop iteration emits structured, correlatable log output instead of ad hoc print statements. |
| [0023](/docs/adr/0023-in-process-error-tracking.md) | In-Process Error Tracking. How unhandled exceptions get captured and surfaced without adding an external dependency the system does not need yet. |

If you are evaluating whether I can operate at a systems level rather than a feature level, this is the fastest
way to check.

## Key Capabilities

- **API key authentication gating every route.** No endpoint, including the one that issues keys, is reachable
  without a valid credential. The only way to mint the first key is a script run locally with direct database
  access, never over HTTP. That closes the exact self-service credential hole that pattern would otherwise leave
  open.
- **Full job lifecycle management.** Explicit state transitions (`Queued to Scheduled to Running to
  Completed/Failed/Cancelled`) with configurable retry policies and priority aware scheduling, plus cancel and
  retry actions reachable directly from the console.
- **Per-job lifecycle history.** Every job has a dedicated detail page (`/jobs/{id}`) showing its full event
  timeline, `JobCreated` through completion, not just current status.
- **Constraint aware best-fit allocator.** Matches workloads to nodes based on resource requirements and labels,
  skipping nodes that are draining or offline.
- **Node draining.** A healthy node can be taken out of scheduling rotation for maintenance without killing it
  outright. The scheduler stops assigning it new work while anything already running on it continues to
  completion.
- **Worker registration and heartbeats.** Registering a node automatically registers a worker against it, so it is
  immediately capable of claiming and executing work.
- **Standalone worker agent with exclusive job ownership.** `scripts/run_agent.py` runs as a real, separate
  process, polling the API over HTTP for assigned work, executing it as a real local subprocess, and heartbeating
  independently for its entire lifetime (ADR 0019). Every worker carries an explicit `managed_by` field
  (`DASHBOARD` or `AGENT`). The in-process scheduler skips any worker marked `AGENT` entirely, so a standalone
  agent's jobs get executed exactly once, never raced against the in-process path.
- **Lease based execution ownership.** When a worker accepts a job, it holds a renewable, expiring lease on that
  job, continuously renewed for the job's entire execution, so retries, reconnects, network failures, and long
  running jobs cannot result in two workers executing the same job.
- **Explicit execution start confirmation.** `POST /workers/{worker_id}/jobs/{job_id}/start` is the one call that
  transitions a job from `Scheduled` to `Running`. Assignment alone does not (ADR 0019).
- **Real subprocess execution with enforced timeouts.** Jobs run as real subprocesses, with a two stage shutdown
  (graceful `SIGTERM`, then `SIGKILL` after a grace period) if a job overruns its execution timeout.
- **Node liveness tracking.** Heartbeat based health checks, automatic detection of offline nodes, and resource
  reclamation when work fails or nodes disappear.
- **Reconciliation with bounded retries.** Jobs abandoned by a dead worker or an offline node get reclaimed back
  to the queue within their retry budget, and fail outright once that budget runs out, so a single unhealthy node
  cannot cause a job to be reassigned and abandoned indefinitely.
- **Domain event recording.** Every lifecycle transition, `JobCreated`, `JobScheduled`, `WorkerAssigned`,
  `LeaseAcquired`, `LeaseReleased`, `JobCompleted`/`JobFailed`, `JobReclaimed`, gets persisted as an immutable
  event at the exact point it happens.
- **Live cluster wide event feed.** `GET /events` and a real time activity feed on the console, polling every 3
  seconds, so the story an individual job tells on its own detail page is also visible cluster wide as it happens.
- **Worker visibility.** A dedicated Workers table showing every registered worker, its status, the node it
  belongs to, what it is running, and when it was last seen.
- **Multi-page operations console.** Real client side routing (`/`, `/nodes`, `/jobs`, `/jobs/{id}`) with active
  route highlighting, built to feel like an operations console, not an admin CRUD template.

## Architecture

I split the system into four layers, with dependencies pointing inward:

**Domain.** `Job`, `Node`, `Worker`, `Lease`, `Event`, and `ApiKey` aggregates enforce their own invariants. The
scheduling algorithm and job lifecycle state machine live here as plain Python, with no imports from FastAPI or
psycopg. Delete the infrastructure layer entirely and the domain tests still pass.

**Application.** Services such as `ScheduleJobService`/`SchedulerService`, `AssignWorkerService`,
`AcquireLeaseService`, `StartJobService`, `DrainNodeService`, `ClusterHealthService`, and
`AuthenticateApiKeyService` coordinate domain objects and repositories without embedding business rules that
belong one layer down. A `WorkerExecutionLoop` drives a worker through executing its assigned job as a real
subprocess, continuously renewing its lease on a background thread for the job's entire runtime, recording the
real outcome, and releasing the lease regardless of that outcome. A renewal that fails means the lease already got
reclaimed elsewhere, so the loop discards its result rather than risk persisting it against another worker's
in-progress or completed work. A `ReconciliationLoop` catches the failure modes the happy path cannot: crashed
workers, expired leases, state left inconsistent by infrastructure failures.

**Infrastructure.** PostgreSQL implementations exist for every repository (`Node`, `Job`, `Worker`, `Lease`,
`Event`, `ApiKey`), written with raw `psycopg` instead of an ORM. That is a deliberate choice to keep query
behavior and transaction boundaries visible rather than abstracted away. `Node`, `Job`, and `Event` additionally
have SQLite implementations for local development. `ApiKey` deliberately does not, since local development already
runs against the same PostgreSQL backend production uses, and a SQLite path would reintroduce the environment
drift that consolidation was built to remove. Every repository gets validated against a shared contract test
suite run against each backend it supports, so switching between implementations, or trusting that they behave
identically, is a tested guarantee rather than an assumption.

**Presentation.** FastAPI endpoints for jobs, nodes, workers, events, cluster health, and API keys that validate
input, call an application service, and return a response. Every route, on every router, requires a valid API key.
No business logic lives in this layer. The frontend mirrors the same discipline: `api/*.ts` typed HTTP calls,
`hooks/*.ts` data fetching hooks, and page/component composition, no business logic embedded in components either.

## A Deliberate Security Decision Worth Naming

The execution engine can run real, arbitrary commands as subprocesses, with real timeout enforcement.
`Job.command` and `Job.exit_code` exist on the domain model and are fully tested at the service layer. I do not
expose them through the public `CreateJobRequest` API, and I enforce that with a test asserting the field's
absence from every response, not a comment.

Building the capability correctly and proving it works, while deferring public exposure until authentication
existed, felt like a more honest state to ship than either skipping the feature or exposing it prematurely
(ADR 0012).

Authentication exists now. Every route, including reads, requires a valid API key, and the only way to mint one
without already holding one is a script run locally with direct database access, never over HTTP (ADR 0015). That
closes the specific gap ADR 0012 named.

`Job.command` still is not broadly exposed. Whether an authenticated caller should be trusted with arbitrary
command execution was a separate decision about scope and blast radius, not infrastructure. I resolved it narrowly
in ADR 0020: a worker can read the one command already assigned to it, nothing broader. The pattern holds either
way. Build it correctly, prove it works, and do not ship exposure until you have actually reasoned through the
risk, not just until the previous blocker is gone.

## Test Coverage

280 tests across domain, application, infrastructure, and API layers, all passing:

- Full domain logic coverage: job lifecycle, retry policy, constraint matching, node and worker liveness, lease
  semantics, node draining and the scheduler's exclusion of draining nodes, and API key issuance, revocation, and
  usage tracking.
- Contract tests proving every repository's in-memory, SQLite (where implemented), and PostgreSQL implementations
  behave identically, including foreign key enforced aggregates such as `Worker` and `Lease`, and specifically
  that lease renewal fails rather than resurrects a lease already reclaimed by reconciliation.
- Application service tests for every use case, including lease acquisition, renewal, release, reconciliation
  repair (both the requeue with retries remaining path and the fail outright once exhausted path), real subprocess
  execution (including a test that genuinely kills a process that ignores `SIGTERM`, forcing `SIGKILL`), and the
  full API key lifecycle from issuance through revocation.
- Event recording tests proving every lifecycle event fires at the correct point, in the correct order, across the
  full job lifecycle: scheduling, assignment, lease acquisition and release, completion, failure, and
  reconciliation reclaim.
- API level tests against real FastAPI endpoints, including the cluster wide event feed, per-job history, and
  every route's auth requirement, verified through a real end-to-end request, not mocked.

CI runs the full suite against a live Postgres service on every push. See [`.github/workflows`](/.github/workflows).

## Running It

```bash
git clone https://github.com/wycliffRotich-dev/aethergrid.git
cd aethergrid
docker compose up --build
```

This starts the API and a Postgres instance. Every route requires an API key, so issue yourself one:

```bash
python scripts/issue_api_key.py "local-dev"
```

Run the console separately:

```bash
cd frontend
npm install
npm run dev
```

## Roadmap

- Fleet scale worker and agent registration, extending the standalone agent model (ADR 0019) beyond a single
  worker per process to coordinated fleets.

## Scope

This is not trying to compete with Kubernetes or Ray at scale. It is my demonstration of how to build a system
that stays understandable as it grows: layered correctly, tested honestly, and documented well enough that someone
else could pick it up and know exactly why every piece is where it is, including the pieces I deliberately left
half built and marked as such.

## License

MIT License.
