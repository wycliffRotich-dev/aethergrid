# ADR 0018: Domain Owns Scheduling Policy

## Status

Accepted

## Context

AetherGrid schedules AI jobs onto compute nodes.

Initially, the `NodeRepository` exposed a `list_available()` operation, allowing the infrastructure layer to determine which nodes were considered eligible for scheduling.

As the project evolved, it became clear that the definition of an "available" node is a business concept rather than a persistence concern.

Future scheduling decisions may consider:

- CPU availability
- Memory availability
- GPU availability
- Node health
- Maintenance mode
- Node labels
- Affinity rules
- Scheduling priorities
- Future scheduling policies

These rules belong to the Domain Model.

## Decision

The `NodeRepository` will expose only persistence operations:

- `save()`
- `list()`
- `get_by_id()`

The repository will no longer determine which nodes are available.

Instead, the Application layer retrieves all registered nodes and delegates the scheduling decision to the Domain Scheduler.

The Scheduler evaluates each node using the business rules defined by the Domain, including `Node.can_host()`.

## Consequences

### Positive

- Scheduling policy remains entirely within the Domain.
- Infrastructure remains responsible only for persistence.
- New scheduling rules can be introduced without modifying repositories.
- PostgreSQL and future persistence implementations remain unaffected by business policy changes.
- Responsibility boundaries become clearer and align with Domain-Driven Design principles.

### Negative

- The scheduler evaluates nodes in memory after retrieval.
- Future large-scale deployments may require optimized repository queries or specialized read models for performance.

These optimizations can be introduced later without changing the domain model.

## Alternatives Considered

### Keep `list_available()` in the repository

Rejected.

This approach gradually moves business policy into the Infrastructure layer, making scheduling behavior dependent on persistence implementations.

### Introduce specification objects

Deferred.

While the Specification Pattern could express scheduling constraints, the current project does not yet require that level of complexity.

The simpler design better matches the current requirements.
