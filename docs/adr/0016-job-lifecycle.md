# ADR 0016: Job Lifecycle

## Status

Accepted

---

## Context

AetherGrid is responsible for orchestrating AI inference workloads across a cluster of compute nodes.

Every submitted workload progresses through a well-defined lifecycle. Different components of the system (REST API, Scheduler, Repository, Telemetry, and Workers) must agree on the meaning of each lifecycle state.

Without a formal lifecycle:

- state transitions become ambiguous;
- telemetry becomes inconsistent;
- invalid transitions become possible;
- business rules become difficult to enforce.

---

## Decision

A Job SHALL progress through the following lifecycle.

```
SUBMITTED
     │
     ▼
QUEUED
 ┌───┴──────┐
 ▼          ▼
FAILED   SCHEDULED
             │
             ▼
          RUNNING
         ┌──┴─────┐
         ▼        ▼
COMPLETED      FAILED
```

A Job MAY be cancelled before execution begins.

Cancellation of a running job requires acknowledgement from the execution backend.

Terminal states are:

- COMPLETED
- FAILED
- CANCELLED

---

## Consequences

Advantages

- Explicit lifecycle
- Deterministic scheduler behavior
- Consistent telemetry
- Clear API semantics
- Easier testing

Trade-offs

- Every state transition must be validated.
- Additional implementation complexity inside the Job entity.

---

## Alternatives Considered

### Generic Status Strings

Rejected.

Free-form strings allow invalid states and transitions.

### Pending / Running / Done

Rejected.

The lifecycle lacks enough detail for scheduling and observability.
