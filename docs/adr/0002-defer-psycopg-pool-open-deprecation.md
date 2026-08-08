# ADR 0005: Defer psycopg_pool ConnectionPool `open` Deprecation Fix

## Status
Accepted

## Context

AetherGrid's PostgreSQL repositories use `psycopg_pool.ConnectionPool`
to manage database connections (see ADR 0004 for why psycopg was
chosen over SQLAlchemy).

Running the Postgres repository contract tests surfaces the
following warning:

DeprecationWarning: the default for the ConnectionPool 'open'
parameter will become 'False' in a future release. Please use
open={True|False} explicitly, or use the pool as context manager
using: `with ConnectionPool(...) as pool: ...`

Today, `ConnectionPool` opens its connections implicitly at
construction time. A future `psycopg_pool` release will change
that default to `False`, meaning the pool will need to be opened
explicitly -- either by passing `open=True`, or by managing the
pool's lifecycle as a context manager.

Fixing this properly is not a one-line change: it requires
deciding how the pool's lifecycle should be managed across the
application (eager open at import time, as today, vs. an explicit
open/close tied to application startup/shutdown). That is an
infrastructure lifecycle decision in its own right, not something
to resolve quietly as a side effect of silencing a warning.

## Decision

Defer the lifecycle change until a deliberate dependency upgrade,
rather than making a rushed change now to clear the warning.

In the meantime, this warning is treated the same way as the one
in ADR 0002: investigated, understood, and documented -- not
suppressed and not ignored.

## Consequences

### Positive
- No behavior change is introduced while AetherGrid is under active
  feature development, avoiding lifecycle churn unrelated to the
  current work.
- The eventual fix (deciding between `open=True` and full
  context-manager-based lifecycle management) is scheduled as
  deliberate work rather than forgotten or silently accepted.
- Consistent with AetherGrid's standing practice: warnings are
  investigated and recorded, never suppressed for the sake of a
  clean terminal.

### Negative
- The application currently depends on `psycopg_pool`'s deprecated
  implicit-open default. This will break outright once a future
  `psycopg_pool` release removes that default, so this must be
  resolved before upgrading past the version that drops it.
- Until resolved, every test run involving `PostgresNodeRepository`
  or `PostgresJobRepository` will continue to emit this warning.

## Alternatives considered

### Fix immediately by passing `open=True`
Deferred, not rejected outright. This is likely the correct
long-term fix, but it does not by itself resolve the underlying
question of where the pool's lifecycle should be owned
(module-level singleton vs. an explicit open/close tied to
FastAPI startup/shutdown events). Making this change now, without
first deciding that, risks locking in an implicit answer to a
question that deserves its own decision.

### Pin psycopg_pool indefinitely to avoid the warning
Rejected. Freezing the dependency version trades a known,
well-understood warning for an unmanaged future problem: missing
security patches and upstream fixes.
