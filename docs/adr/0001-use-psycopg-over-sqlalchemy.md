# ADR 0004: Use psycopg over SQLAlchemy

## Status

Accepted

## Context

AetherGrid requires a persistence layer for PostgreSQL-backed repositories.

The project follows a clean architecture approach where domain entities and application services should remain independent from infrastructure frameworks.

Using an ORM such as SQLAlchemy would introduce an additional abstraction layer between repository logic and PostgreSQL. For this project, direct SQL access provides:

- explicit database interactions
- easier auditing of queries
- predictable performance characteristics
- alignment with the repository pattern
- reduced infrastructure complexity

## Decision

We will use PostgreSQL with psycopg as the database access layer.

Database schemas will be managed using plain SQL files rather than ORM migrations.

Repositories will own persistence behavior while domain entities remain framework-independent.

## Consequences

### Positive

- Full control over SQL queries
- Clear separation between domain and infrastructure
- No ORM coupling
- Easier database reasoning for production operations

### Negative

- Schema evolution requires manual SQL management
- More responsibility around query maintenance
- Less automatic model generation

## Alternatives considered

### SQLAlchemy ORM

Rejected because the project does not require ORM-level abstraction and prefers explicit SQL control.

### Alembic migrations

Rejected for now because schema management remains intentionally lightweight during this development stage.
