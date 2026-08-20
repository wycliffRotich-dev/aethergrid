<p align="center">
  <img src="docs/assets/logo.png" alt="AetherGrid logo" width="480">
</p>

<p align="center">
  A distributed AI workload orchestrator built around the problems that make scheduling hard at scale: exclusive execution ownership under failure, reconciliation after partial failures, and enforced resource limits. Not a CRUD tutorial with a scheduler theme.
</p>

<p align="center">
  <a href="#test-coverage"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/wycliffRotich-dev/4b35dff5cea5aa68433713c36c3108bb/raw/aethergrid-test-badge.json" alt="Tests"></a>
  <a href="#engineering-decision-records"><img src="https://img.shields.io/badge/ADRs-24-blueviolet" alt="ADRs"></a>
  <a href="#license"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/PostgreSQL-336791?logo=postgresql&logoColor=white" alt="PostgreSQL"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black" alt="React"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
  <a href="https://aethergrid-dashboard.onrender.com"><img src="https://img.shields.io/badge/Live%20Demo-aethergrid--dashboard.onrender.com-brightgreen?logo=render&logoColor=white" alt="Live Demo"></a>
</p>

AetherGrid takes workloads, matches them against available compute nodes based on resource requirements and constraints, and manages the full lifecycle: queued, scheduled, running, completed, failed, retried, cancelled. Jobs run through workers registered against nodes, and job execution ownership is enforced through time-bound leases rather than a simple assignment flag. Every route requires API key authentication, including the endpoint that issues keys.

**Try it live**: the full console is deployed and reachable at [aethergrid-dashboard.onrender.com](https://aethergrid-dashboard.onrender.com) with real Postgres, real auth, and real API-key-gated endpoints.

---

## Why This Exists

Most scheduler side-projects are a single `main.py` script wrapped in a `while True` loop polling an in-memory dictionary. They work fine, right up until you need to swap the persistence engine, add a new constraint type, or figure out why a job silently disappeared, or why two workers picked up the same job at once.

AetherGrid was built around one rule: **the domain logic doesn't know or care where the data lives.** Jobs, nodes, workers, and the allocation algorithm are pure Python with zero infrastructure dependencies. The database is a detail, not the foundation. This project is a concrete demonstration that these architectural patterns aren't just conference-talk vocabulary; they're guardrails that keep a codebase understandable as it grows, and as its correctness requirements get harder.

---

## Engineering Decision Records

Every non-obvious decision in this codebase, why a domain rule lives where it does, why an obvious-looking shortcut was rejected, what broke and how it got fixed, is written down at the moment it was made, not reconstructed afterward for a portfolio. 24 ADRs live in [`/docs/adr`](docs/adr). A few worth reading directly if you want to see the reasoning, not just the conclusion:

- [**ADR 0007 - Reconciliation Loop**](docs/adr/0007-reconciliation-loop.md): how the system detects and repairs state left inconsistent by dead workers and expired leases, instead of assuming the happy path is the only path.
- [**ADR 0011 - Job Reclaim and Reconciliation Repair**](docs/adr/0011-job-reclaim-and-reconciliation-repair.md): closing a real race condition where a dying worker's lease renewal could land after reconciliation had already started reassigning its work.
- [**ADR 0012 - Real Job Execution**](docs/adr/0012-real-job-execution.md): building genuine subprocess execution with enforced timeouts, then deliberately keeping it unreachable from the public API until the system had authentication, and proving that absence with a test rather than a comment.
- [**ADR 0014 - Continuous Lease Renewal**](docs/adr/0014-continuous-lease-renewal.md): why a lease is renewed continuously for a job's entire runtime instead of once at acquisition.
- [**ADR 0015 - API Key Authentication**](docs/adr/0015-api-key-authentication.md): why opaque server-issued tokens were chosen over JWTs for a system that needs instant revocation, and why building authentication still didn't answer whether `Job.command` should be exposed, that question stayed open until [ADR 0020](docs/adr/0020-expose-job-command-to-authenticated-agents.md), which resolved it narrowly: a worker can read the one command already assigned to it, nothing broader.
- [**ADR 0018 - Domain Owns Scheduling Policy**](docs/adr/0018-domain-owns-scheduling-policy.md): why `list_available()` moved out of the repository entirely, since deciding which nodes are eligible for scheduling is a business rule, not a persistence concern, and letting infrastructure decide that would have made scheduling behavior dependent on which database backend was running.
- [**ADR 0019 - Standalone Worker Agent Process**](docs/adr/0019-standalone-worker-agent-process.md): replacing in-process job execution with a real out-of-process agent that confirms its own execution start over the network, and why pull-based polling was chosen over push delivery, since it reuses reconciliation this codebase already trusts instead of introducing new failure and delivery-guarantee logic.

If you're evaluating whether someone can operate at a systems level rather than a feature level, this is the fastest way to check.

---

## Key Capabilities

- **API key authentication gating every route**: no endpoint in the system, including the one that issues keys, is reachable without a valid credential. The only way to mint the first key is a script run locally with direct database access, never over HTTP, closing the exact self-service-credential hole that pattern would otherwise leave open
- **Job lifecycle management**: explicit state transitions (Queued → Scheduled → Running → Completed/Failed/Cancelled) with configurable retry policies and priority-aware scheduling, plus cancel and retry actions reachable from the dashboard
- **Per-job lifecycle history**: every job has a dedicated detail page (`/jobs/{id}`) showing its full real event timeline, `JobCreated` through completion, not just its current status
- **Constraint-aware best-fit allocator**: matches workloads to nodes based on resource requirements and labels, while skipping nodes that are draining or offline
- **Node draining**: a healthy node can be taken out of scheduling rotation for maintenance without killing it outright; the scheduler stops assigning it new work while anything already running on it continues to completion
- **Worker registration and heartbeats**: registering a node automatically registers a worker against it, so it's immediately capable of claiming and executing work, not just existing as unused capacity
- **Standalone worker agent with exclusive job ownership**: `scripts/run_agent.py` runs as a real, separate process, polling the API over HTTP for assigned work, executing it as a real local subprocess, and heartbeating on its own background thread for the agent's entire lifetime, independent of whatever job it's currently executing (see [ADR 0019](docs/adr/0019-standalone-worker-agent-process.md)). This replaces the dashboard's client-side heartbeat as the liveness mechanism for any worker running it; a worker with no agent process attached still falls back to node liveness alone. Every worker is tagged with an explicit `managed_by` field set at registration (`DASHBOARD` or `AGENT`); the in-process scheduler loop skips any worker marked `AGENT` entirely, so a standalone agent's jobs are executed exactly once, by the agent, never raced against the in-process path.
- **Lease-based execution ownership**: when a worker accepts a job, it holds a renewable, expiring lease on that job, continuously renewed for the job's entire execution, so retries, reconnects, network failures, and jobs that simply run long can't result in two workers executing the same job
- **Explicit execution-start confirmation**: `POST /workers/{worker_id}/jobs/{job_id}/start` lets whatever is actually executing a job, the in-process scheduler loop for dashboard-managed workers, a standalone agent for agent-managed ones (ADR 0019), confirm execution has genuinely begun. This is the one call that transitions a job from `Scheduled` to `Running`; assignment alone no longer does (see [ADR 0019](docs/adr/0019-standalone-worker-agent-process.md))
- **Real subprocess execution with enforced timeouts**: jobs with a command run as real subprocesses, with a two-stage shutdown (graceful `SIGTERM`, then `SIGKILL` after a grace period) if a job overruns its execution timeout
- **Node liveness tracking**: heartbeat-based health checks, automatic detection of offline nodes, and resource reclamation when work fails or nodes disappear
- **Reconciliation with bounded retries**: jobs abandoned by a dead worker or an offline node are reclaimed back to the queue within their retry budget, and fail outright once that budget is exhausted, so a single unhealthy node can't cause a job to be reassigned and abandoned indefinitely, with the reclaim ordered to close a real race where a dying worker's renewal could land after reconciliation had already started reassigning its lease
- **Domain event recording**: every lifecycle transition a job goes through, `JobCreated`, `JobScheduled`, `WorkerAssigned`, `LeaseAcquired`, `LeaseReleased`, `JobCompleted`/`JobFailed`, and `JobReclaimed`, is persisted as an immutable event at the exact point it happens
- **Live cluster-wide event feed**: `GET /events` and a real-time Activity Feed on the dashboard, polling every 3 seconds, so the story an individual job tells on its own detail page is also visible as it happens across the whole cluster
- **Worker visibility**: a dedicated Workers table showing every registered worker, its status, the node it belongs to, what it's running, and when it was last seen
- **Multi-page dashboard**: real client-side routing (`/`, `/nodes`, `/jobs`, `/jobs/{id}`) instead of a single page, with active-route highlighting in the sidebar

---

## Architecture

The system is split into four layers, with dependencies pointing inward:

**Domain**: `Job`, `Node`, `Worker`, `Lease`, `Event`, and `ApiKey` aggregates enforce their own invariants. The scheduling algorithm and job lifecycle state machine live here as plain Python, with no imports from FastAPI or psycopg. Delete the infrastructure layer entirely and the domain tests still pass.

**Application**: Services such as `ScheduleJobService`/`SchedulerService`, `AssignWorkerService`, `AcquireLeaseService`, `StartJobService`, `DrainNodeService`, `ClusterHealthService`, and `AuthenticateApiKeyService` coordinate domain objects and repositories without embedding business rules that belong one layer down. A `WorkerExecutionLoop` drives a worker through executing its assigned job as a real subprocess, continuously renewing its lease on a background thread for the job's entire runtime, recording the real outcome, and releasing the lease regardless of that outcome. A renewal that fails means the lease has already been reclaimed elsewhere, and the loop discards its result rather than risk persisting it against another worker's in-progress or completed work. A `ReconciliationLoop` catches the failure modes the happy path can't: crashed workers, expired leases, state left inconsistent by infrastructure failures.

**Infrastructure**: PostgreSQL implementations exist for every repository (`Node`, `Job`, `Worker`, `Lease`, `Event`, `ApiKey`), written with raw `psycopg` instead of an ORM, a deliberate choice to keep query behavior and transaction boundaries visible rather than abstracted away. `Node`, `Job`, and `Event` additionally have SQLite implementations for local development; `ApiKey` deliberately does not, since local development already runs against the same PostgreSQL backend production uses, and a SQLite path would reintroduce the environment drift that consolidation was built to remove. Every repository is validated against a shared **contract test suite** run against each backend it supports, so switching between implementations, or trusting that they behave identically, is a tested guarantee rather than an assumption.

**Presentation**: FastAPI endpoints for jobs, nodes, workers, events, cluster health, and API keys that validate input, call an application service, and return a response. Every route, on every router, requires a valid API key. No business logic lives in this layer. The frontend mirrors the same discipline: `api/*.ts` typed HTTP calls, `hooks/*.ts` data-fetching hooks, and page/component composition, no business logic embedded in components either.

Every non-obvious decision, why domain owns scheduling instead of application, why raw psycopg over an ORM, how job lifecycle transitions are enforced, why leases exist instead of a simple assignment field, why renewal is a strict update rather than an upsert, why opaque tokens were chosen over JWTs, why job commands are deliberately still not exposed over the public API, and why that boundary was later reopened narrowly for workers reading their own assigned job ([ADR 0020](docs/adr/0020-expose-job-command-to-authenticated-agents.md)), is documented as an ADR in [`/docs/adr`](docs/adr).

---

## A Deliberate Security Decision Worth Naming

The execution engine can run real, arbitrary commands as subprocesses, with real timeout enforcement. `Job.command` and `Job.exit_code` exist on the domain model and are fully tested at the service layer. They are **not** exposed through the public `CreateJobRequest` API, and this is enforced by a test asserting the field's absence from every response, not left as a comment.

Building the capability correctly and proving it works, while deferring public exposure until authentication existed, was judged a more honest state to ship than either skipping the feature or exposing it prematurely (ADR 0012).

Authentication now exists. Every route, including reads, requires a valid API key, and the only way to mint one without already holding one is a script run locally with direct database access, never over HTTP (ADR 0015). That closes the specific gap ADR 0012 named.

`Job.command` still isn't exposed. Whether an authenticated caller should be trusted with arbitrary command execution is a separate decision about scope and blast radius, not infrastructure, and it hasn't been made yet. The pattern holds either way: build it correctly, prove it works, and don't ship the exposure until the actual risk has been reasoned through, not just until the previous blocker is gone.

---

## Test Coverage

280 tests across domain, application, infrastructure, and API layers, all passing:

- Full domain logic coverage: job lifecycle, retry policy, constraint matching, node and worker liveness, lease semantics, node draining and the scheduler's exclusion of draining nodes, and API key issuance, revocation, and usage tracking
- Contract tests proving every repository's in-memory, SQLite (where implemented), and PostgreSQL implementations behave identically, including foreign-key-enforced aggregates such as `Worker` and `Lease`, and specifically that lease renewal fails rather than resurrects a lease already reclaimed by reconciliation
- Application service tests for every use case, including lease acquisition, renewal, release, reconciliation repair (both the requeue-with-retries-remaining path and the fail-outright-once-exhausted path), real subprocess execution (including a test that genuinely kills a process that ignores `SIGTERM`, forcing `SIGKILL`), and the full API key lifecycle from issuance through revocation
- Event recording tests proving every lifecycle event fires at the correct point, in the correct order, across the full job lifecycle, scheduling, assignment, lease acquisition and release, completion, failure, and reconciliation reclaim
- API-level tests against real FastAPI endpoints, including the cluster-wide event feed, per-job history, and every route's auth requirement, verified through a real end-to-end request, not mocked

```bash
pytest
```

---

## Running It

```bash
git clone https://github.com/wycliffRotich-dev/aethergrid.git
cd aethergrid
docker compose up --build
```

This starts the API and a Postgres instance. Issue yourself a key before calling anything, every route requires one:

```bash
python scripts/issue_api_key.py "local-dev"
```

Run the frontend separately:

```bash
cd frontend
npm install
npm run dev
```

CI runs the full test suite against a live Postgres service on every push. See `.github/workflows`.

---

## Scope

This isn't trying to compete with Kubernetes or Ray at scale. It's a demonstration of how to build a system that stays understandable as it grows: layered correctly, tested honestly, and documented well enough that someone else could pick it up and know exactly why every piece is where it is, including the pieces that are deliberately half-built and marked as such.

---

<p align="right">
<strong>Let's connect</strong>&nbsp;&nbsp;&nbsp;<a href="tel:+254745275288"><img src="https://img.icons8.com/ios-filled/32/25D366/phone.png" alt="Call" /></a>&nbsp;&nbsp;<a href="https://wa.me/254745275288"><img src="https://img.icons8.com/ios-filled/32/25D366/whatsapp.png" alt="WhatsApp" /></a>&nbsp;&nbsp;<a href="https://linkedin.com/in/rotichkipleting"><img src="https://img.icons8.com/ios-filled/32/0A66C2/linkedin.png" alt="LinkedIn" /></a>&nbsp;&nbsp;<a href="mailto:celestinerotich969@gmail.com"><img src="https://img.icons8.com/ios-filled/32/EA4335/gmail.png" alt="Email" /></a>
</p>
