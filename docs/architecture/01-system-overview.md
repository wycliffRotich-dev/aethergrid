# System Overview

```mermaid
flowchart LR

User["User"]

Browser["React Dashboard"]

Agent["Standalone Agent"]

API["FastAPI"]

Application["Application Layer"]

Domain["Domain Layer"]

Infrastructure["Infrastructure Layer"]

DB[(PostgreSQL)]

User --> Browser
Browser --> API
Agent --> API
API --> Application
Application --> Domain
Domain --> Infrastructure
Infrastructure --> DB
```

The standalone agent (`scripts/run_agent.py`) is a separate
process that authenticates and calls the API directly, the same
way the dashboard does, not through the browser. It registers,
polls for work, executes jobs as real local subprocesses, and
reports outcomes over the same authenticated REST surface.
