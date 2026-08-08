# ADR-0006: Worker Registration API

**Status:** Accepted

**Date:** 2026-07-12

---

## Context

AetherGrid follows a strict Domain-Driven Design (DDD) architecture.

A `Worker` is a domain entity that belongs to a `Node` and is managed by
the server. Initially, the Worker Registration API accepted both a worker
identifier and a node identifier:

```http
POST /workers

{
    "id": "worker-1",
    "node_id": "node-1"
}
```

During the introduction of strongly typed value objects (`WorkerId`,
`NodeId`), this design revealed several architectural problems.

The client became responsible for generating the identity of a domain
entity.

This violated one of the design principles adopted throughout AetherGrid:

> Entity identity is part of the Domain Model and must be controlled by the
> Domain, not external clients.

Allowing clients to create identifiers also introduced several concerns:

- Duplicate identifiers.
- Client-controlled identity.
- Tighter coupling between clients and internal implementation.
- Weaker aggregate consistency.
- Difficult migration to distributed persistence.
- Tests depending on implementation details.

---

## Decision

The server is responsible for creating Worker identifiers.

The registration endpoint now accepts only the identifier of an existing
Node.

```http
POST /workers

{
    "node_id": "<node-id>"
}
```

The application service creates a new Worker using the Domain value object.

```python
worker = Worker(
    id=WorkerId.new(),
    node=node,
)
```

The newly created Worker is persisted through the `WorkerRepository`.

The API returns the generated identifier to the client.

```json
{
    "id": "<generated-worker-id>",
    "status": "STARTING"
}
```

---

## Rationale

This decision keeps identity generation inside the Domain Model.

The client requests that a Worker be created.

The server decides:

- how identifiers are generated;
- which identifier implementation is used;
- when identity is assigned;
- how uniqueness is guaranteed.

This preserves the separation between Presentation,
Application, Domain and Infrastructure layers.

The client expresses intent.

The Domain creates identity.

---

## Consequences

### Positive

- Preserves DDD boundaries.
- Entity identity remains a domain concern.
- Supports strongly typed `WorkerId`.
- Prevents client-generated duplicate identifiers.
- Simplifies persistence.
- Simplifies future PostgreSQL migration.
- Simplifies distributed scheduling.
- Easier event sourcing.
- Easier CQRS adoption.
- Easier horizontal scaling.
- Cleaner API contract.
- Better encapsulation.

### Negative

- Existing clients must stop sending worker identifiers.
- Existing tests expecting client-generated identifiers require updating.
- Clients must use the identifier returned by the API.

---

## Alternatives Considered

### Alternative A — Client Generates WorkerId

Rejected.

Reasons:

- Weakens DDD boundaries.
- Makes identity an API concern.
- Allows arbitrary identifiers.
- Couples external clients to internal implementation.

---

### Alternative B — Sequential Database IDs

Rejected.

Reasons:

- Couples the Domain to persistence.
- Makes future distributed deployments harder.
- Leaks infrastructure concerns into the Domain.

---

### Alternative C — Server Generates UUID (Accepted)

Accepted.

Reasons:

- Infrastructure-independent.
- Globally unique.
- Compatible with distributed systems.
- Consistent with Domain-Driven Design.
- Keeps identity generation inside the Domain.

---

## Impact

This ADR affects:

- Domain
    - Worker
    - WorkerId

- Application
    - CreateWorkerService

- Presentation
    - Worker Registration API

- Infrastructure
    - WorkerRepository implementations

- Tests
    - Worker registration tests

---

## Compliance

This decision aligns with the architectural principles adopted by
AetherGrid:

- Domain-Driven Design (DDD)
- Clean Architecture
- Rich Domain Model
- Repository Pattern
- Dependency Inversion Principle
- Strongly Typed Value Objects
- Infrastructure Independence

---

## References

- Eric Evans — *Domain-Driven Design: Tackling Complexity in the Heart of Software*
- Vaughn Vernon — *Implementing Domain-Driven Design*
- Robert C. Martin — *Clean Architecture*
- Martin Fowler — *Patterns of Enterprise Application Architecture*
