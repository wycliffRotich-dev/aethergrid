<p align="center">
  <img src="docs/assets/logo.png" alt="AetherGrid logo" width="480">
</p>

<p align="center">
  A distributed AI workload scheduler built to demonstrate Clean Architecture, Domain-Driven Design, and real infrastructural decoupling.
</p>

<p align="center">
  <a href="#test-coverage"><img src="https://img.shields.io/badge/tests-193%20passed-brightgreen" alt="Tests"></a>
  <a href="#license"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/PostgreSQL-336791?logo=postgresql&logoColor=white" alt="PostgreSQL"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black" alt="React"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
</p>

AetherGrid takes workloads, matches them against available compute nodes based on resource requirements and constraints, and manages the full lifecycle: queued, scheduled, running, completed, failed, retried, cancelled. Jobs run through workers registered against nodes, and job execution ownership is enforced through time-bound leases rather than a simple assignment flag.

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.12 |
| **API Framework** | FastAPI |
| **Database** | PostgreSQL (raw `psycopg`, no ORM), with SQLite for select repositories in local development |
| **Frontend** | React + TypeScript + Vite, React Router, TanStack Query |
| **Testing** | pytest, contract testing across repository implementations |
| **CI/CD** | GitHub Actions |
| **Containerization** | Docker + Docker Compose |
| **Architecture** | Clean Architecture, Domain-Driven Design, Repository Pattern, SOLID |

---

## Why This Exists

Most scheduler side-projects are a single `main.py` script wrapped in a `while True` loop polling an in-memory dictionary. They work fine, right up until you need to swap the persistence engine, add a new constraint type, or figure out why a job silently disappeared, or why two workers picked up the same job at once.

AetherGrid was built around one rule: **the domain logic doesn't know or care where the data lives.** Jobs, nodes, workers, and the allocation algorithm are pure Python with zero infrastructure dependencies. The database is a detail, not the foundation. This project is a concrete demonstration that these architectural patterns aren't just conference-talk vocabulary; they're guardrails that keep a codebase understandable as it grows, and as its correctness requirements get harder.

---

## Key Capabilities

- **Job lifecycle management**: explicit state transitions (Queued → Scheduled → Running → Completed/Failed/Cancelled) with configurable retry policies and priority-aware scheduling, plus cancel and retry actions reachable from the dashboard
- **Per-job lifecycle history**: every job has a dedicated detail page (`/jobs/{id}`) showing its full real event timeline, `JobCreated` through completion, not just its current status
- **Constraint-aware best-fit allocator**: matches workloads to nodes based on resource requirements and labels, while skipping nodes that are draining or offline
- **Node draining**: a healthy node can be taken out of scheduling rotation for maintenance without killing it outright; the scheduler stops assigning it new work while anything already running on it continues to completion
- **Worker registration and heartbeats**: registering a node automatically registers a worker against it, so it's immediately capable of claiming and executing work, not just existing as unused capacity
- **Persistent liveness while the dashboard is open**: both workers and nodes are kept alive on a client-side heartbeat interval for as long as the dashboard tab is open, standing in for a real worker/node agent process; close the tab and liveness decays exactly as it should
- **Lease-based execution ownership**: when a worker accepts a job, it holds a renewable, expiring lease on that job, continuously renewed for the job's entire execution, so retries, reconnects, network failures, and jobs that simply run long can't result in two workers executing the same job
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

**Domain**: `Job`, `Node`, `Worker`, `Lease`, and `Event` aggregates enforce their own invariants. The scheduling algorithm and job lifecycle state machine live here as plain Python, with no imports from FastAPI or psycopg. Delete the infrastructure layer entirely and the domain tests still pass.

**Application**: Services such as `ScheduleJobService`/`SchedulerService`, `AssignWorkerService`, `AcquireLeaseService`, `DrainNodeService`, and `ClusterHealthService` coordinate domain objects and repositories without embedding business rules that belong one layer down. A `WorkerExecutionLoop` drives a worker through executing its assigned job as a real subprocess, continuously renewing its lease on a background thread for the job's entire runtime, recording the real outcome, and releasing the lease regardless of that outcome. A renewal that fails means the lease has already been reclaimed elsewhere, and the loop discards its result rather than risk persisting it against another worker's in-progress or completed work. A `ReconciliationLoop` catches the failure modes the happy path can't: crashed workers, expired leases, state left inconsistent by infrastructure failures.

**Infrastructure**: PostgreSQL implementations exist for every repository (`Node`, `Job`, `Worker`, `Lease`, `Event`), written with raw `psycopg` instead of an ORM, a deliberate choice to keep query behavior and transaction boundaries visible rather than abstracted away. `Node`, `Job`, and `Event` additionally have SQLite implementations for local development. Every repository is validated against a shared **contract test suite** run against each backend it supports, so switching between implementations, or trusting that they behave identically, is a tested guarantee rather than an assumption.

**Presentation**: FastAPI endpoints for jobs, nodes, workers, events, and cluster health that validate input, call an application service, and return a response. No business logic lives here. The frontend mirrors the same discipline: `api/*.ts` typed HTTP calls, `hooks/*.ts` data-fetching hooks, and page/component composition, no business logic embedded in components either.

Every non-obvious decision, why domain owns scheduling instead of application, why raw psycopg over an ORM, how job lifecycle transitions are enforced, why leases exist instead of a simple assignment field, why renewal is a strict update rather than an upsert, why job commands are deliberately not exposed over the public API yet, is documented as an ADR in `/docs/adr`.

---

## A Deliberate Security Decision Worth Naming

The execution engine can run real, arbitrary commands as subprocesses, with real timeout enforcement. `Job.command` and `Job.exit_code` exist on the domain model and are fully tested at the service layer. They are **not** exposed through the public `CreateJobRequest` API, and this is enforced by a test asserting the field's absence from every response, not left as a comment.

Exposing arbitrary caller-supplied commands over an endpoint with no authentication would mean shipping unauthenticated remote code execution. Building the capability correctly and proving it works, while deferring public exposure until authentication exists, was judged a more honest state to ship than either skipping the feature or exposing it prematurely. See ADR 0012.

---

## Test Coverage

193 tests across domain, application, infrastructure, and API layers:

- Full domain logic coverage: job lifecycle, retry policy, constraint matching, node and worker liveness, lease semantics, node draining and the scheduler's exclusion of draining nodes
- Contract tests proving every repository's in-memory, SQLite (where implemented), and PostgreSQL implementations behave identically, including foreign-key-enforced aggregates such as `Worker` and `Lease`, and specifically that lease renewal fails rather than resurrects a lease already reclaimed by reconciliation
- Application service tests for every use case, including lease acquisition, renewal, release, reconciliation repair (both the requeue-with-retries-remaining path and the fail-outright-once-exhausted path), and real subprocess execution (including a test that genuinely kills a process that ignores `SIGTERM`, forcing `SIGKILL`)
- Event recording tests proving every lifecycle event fires at the correct point, in the correct order, across the full job lifecycle, scheduling, assignment, lease acquisition and release, completion, failure, and reconciliation reclaim
- API-level tests against real FastAPI endpoints, including the cluster-wide event feed and per-job history

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

This starts the API and a Postgres instance. Run the frontend separately:

```bash
cd frontend
npm install
npm run dev
```

CI runs the full test suite against a live Postgres service on every push. See `.github/workflows`.

---

## What's Next

- A dedicated Workers page and route, worker visibility currently lives on the dashboard overview rather than having its own place in navigation, unlike Nodes and Jobs
- A real worker/node agent process; liveness today is honestly approximated by the dashboard heartbeating on the client's behalf while a tab is open, which is transparent about its limits but isn't a substitute for an actual agent
- Hardening the API for public deployment (rate limiting, structured logging, error tracking, authentication), which also unblocks safely exposing real job commands over the public API rather than keeping them internal-only
- Live cloud deployment with CI/CD auto-deploy on merge

---

## Scope

This isn't trying to compete with Kubernetes or Ray at scale. It's a demonstration of how to build a system that stays understandable as it grows: layered correctly, tested honestly, and documented well enough that someone else could pick it up and know exactly why every piece is where it is, including the pieces that are deliberately half-built and marked as such.

---

## License

MIT License.
