# ADR 0008: Persist Domain Events Through Repository Abstractions

## Status

Accepted

## Context

AetherGrid records domain events whenever important changes occur within the system. Creating a job, scheduling it, or transitioning it through its lifecycle all produce events that describe what happened and when it happened.

Initially, those events lived only in memory. That was sufficient while the event log existed purely to support application behavior during a single process lifetime. The limitation became obvious once event history became a first-class feature. Restarting the application meant the entire history disappeared.

Jobs and nodes already avoided this problem by depending on repository contracts instead of concrete storage implementations. The event subsystem should follow the same architectural rule. Otherwise, one part of the application would remain tightly coupled to its persistence mechanism while everything else stayed infrastructure-agnostic.

## Decision

Introduce persistent event storage through the existing repository abstraction.

The `EventRepository` interface remains the only dependency used by application services. Infrastructure provides concrete implementations for each supported storage backend.

The project now includes:

- `InMemoryEventRepository`
- `SqliteEventRepository`

The SQLite implementation stores the complete `Event` aggregate, including its identifier, aggregate metadata, timestamp, payload, and event type. Repository contract tests ensure both implementations expose identical behaviour and can be substituted without changing application logic.

Repository selection is performed during dependency injection based on the configured storage backend.

## Consequences

Event persistence now follows the same architectural pattern as jobs and nodes. Application services remain independent of storage technology, while infrastructure is responsible for persistence.

Historical events survive application restarts when SQLite is enabled. That makes the event log useful for debugging, auditing, and future reconciliation workflows.

This decision also reduces future work. Supporting another backend, such as PostgreSQL, only requires implementing the same repository contract and satisfying the existing contract tests. No application or domain code needs to change.

Most importantly, the architecture stays consistent. Every major persistence concern in AetherGrid now follows the same design principles instead of introducing special cases for individual aggregates.
