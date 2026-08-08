# ADR 0009: Reconstruct Identifier Value Objects from Persisted State

## Status

Accepted

## Context

AetherGrid follows Domain-Driven Design and models every aggregate identifier as an immutable Value Object. Identifiers are created inside the domain when new aggregates are introduced, but repositories also need to rebuild existing objects from persistent storage.

While implementing the PostgreSQL Event Repository we discovered that `EventId` could create new identifiers but could not reconstruct one that had already been stored. The repository therefore had no consistent way to hydrate an `Event` from the database.

Other identifier types already supported reconstruction. Leaving `EventId` as an exception would force infrastructure code to bypass the Value Object or duplicate identity logic outside the domain.

## Decision

Every identifier Value Object will expose two construction paths.

- `new()` creates a brand-new identifier for newly created domain objects.
- `from_string()` reconstructs an existing identifier from persisted state.

`from_string()` is responsible for validating the supplied value before creating the Value Object. Repositories should always use this method when rebuilding entities from storage instead of constructing identifiers directly.

## Consequences

The domain now has a consistent lifecycle for identifiers regardless of where they originate.

Repositories remain responsible only for persistence and object reconstruction. They no longer contain identifier validation or creation logic.

Adding new identifier types becomes straightforward because every identifier follows the same contract. This keeps repository implementations predictable and reduces the chance of inconsistent behavior across aggregates.

This decision also strengthens the boundary between the domain and infrastructure. Identity rules stay inside the Value Objects where they belong, while persistence layers simply translate between database rows and domain objects.
