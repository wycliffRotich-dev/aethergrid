# ADR 0082: Enforce the Layer Dependencies With a Test

## Status

Accepted. A test fails when a module in `app/` imports across a layer
boundary that the rules do not allow. No import is excepted: the two
that broke a rule were fixed in the same change.

Related: ADR 0046 and ADR 0078.

## Context

`app/` is organized as four layers: domain, application,
infrastructure and presentation. The intent is that dependencies point
inward. `docs/architecture/02-clean-architecture.md` is listed as the
dependency boundaries, and it was empty. No test inspected the imports
of `app/` for this, so the rule held only while each author kept it.

A survey of `app/` at b1f7f13, before this change, found:

1. `get_job_service.py` imported the domain through five relative
   imports, `from ...domain`, that climb out of their package. A grep
   for `app.domain` did not see them. They are the only relative
   imports in `app/` that leave their package.
2. `api.py` imported `psycopg_pool`, a library that only the
   infrastructure layer and the composition root may import, for
   one reason: `health()` was annotated with the pool it was
   handed, and FastAPI needs that name at runtime. Nothing in
   `api.py` needs the type, and the lifespan only calls methods on
   what the composition root returns.
3. Two infrastructure modules, the leadership adapters of ADR 0078,
   import the `SchedulerLeadership` port from the application layer.
   Each adapter points at the port it implements.
4. Everything else followed the rules in the Decision below.

## Decision

1. `tests/architecture/test_layer_dependencies.py` parses every module
   in `app/` with `ast` and fails on a violation. It reads imports
   anywhere in a module, including inside functions and under
   `TYPE_CHECKING`, and resolves a relative import to its absolute name
   before it judges it. It does not import `app`, so it needs no
   database.
2. Each layer may import its own modules and the layers listed here:
   - domain: no other layer.
   - application: the domain.
   - infrastructure: the domain.
   - presentation: the application and the domain.

   `app/main.py` may import only `app.presentation.api`. A module that
   is in no layer fails the test.
3. Two exceptions are named in the test. `dependencies.py` in
   `app/presentation`, the composition root, may also import
   infrastructure and `psycopg_pool`. Infrastructure may import one
   application module, `app.application.scheduler_leadership`, the port
   that its leadership adapters implement.
4. The domain and the application import only the standard library.
   Infrastructure adds `psycopg` and `psycopg_pool`. Presentation adds
   `fastapi`, `pydantic` and `starlette`.
5. A relative import may not leave its own package, because the layer
   it reaches would then be hidden in the dots.
6. `__import__` and `import_module` are not used in `app/`. A module
   named by a string is a dependency that no import check can see.
7. There is no list of tolerated imports. The test has one rule set and
   no escape hatch, so a violation is fixed and not recorded.
8. `get_job_service.py` now uses absolute imports. `api.py` no longer
   imports `psycopg_pool`. The composition root gets
   `check_database_reachable(timeout_seconds)`, which does nothing
   without a pool and otherwise runs `SELECT 1` on a connection from
   the pool within the caller's timeout. `health()` calls it with the
   same 2 second timeout as before. The 200 and 503 bodies do not
   change, and the 503 still carries only the exception class name.

## Evidence

- Before the move, four tests for `GET /health` were written against
  the unmodified code, and they passed: healthy with no pool, one
  `SELECT 1` on the 2 second timeout, and a 503 that names only the
  exception class for a connection that times out and for a query that
  fails. With the failure not caught, 2 of them fail. With the pool's
  30 second default used, 1 fails. They did not exist before.
- The moved function was mutated twice. Ignoring the caller's timeout
  fails 1 test, and not skipping a missing pool fails 1.
- On main, with relative imports, the layer test failed and named
  `get_job_service.py`. With absolute imports it passes. Putting
  `import psycopg_pool` back into `api.py` fails it again, naming the
  file and line.
- Eleven throwaway modules, each breaking one rule, were all caught:
  the domain importing the application, the application importing
  `psycopg`, infrastructure importing an application module that is not
  the port, presentation importing infrastructure, presentation
  importing `psycopg_pool`, a module in no layer, a relative import
  that climbs out of its package, an import inside a function, and
  three forms of dynamic import.
- 18 table tests call the two rule functions directly, so loosening a
  rule fails a test even while `app/` complies. With the composition
  root exception removed, 2 of them fail. With the dynamic import check
  turned off, its probe is no longer caught.
- The full suite passes (1072).

## Consequences

- A new import across a boundary fails the suite, and CI with it,
  wherever in the module it is written.
- The rules sit in one file. Changing a rule is a reviewed edit, and a
  change to the architecture itself needs an ADR.
- A new top level package under `app/` fails until the test places it
  in a layer.
- `docs/architecture/02-clean-architecture.md` now states the rules and
  points to the test.
- `/health` no longer takes the pool as a dependency. Overriding
  `get_connection_pool` no longer changes what it checks, and its tests
  patch the pool that the composition root holds.

## Not Claimed

- That nothing couples the layers at runtime. The test reads imports,
  so a dependency handed in as an argument, or a name that a framework
  looks up from a string, is not seen.

## Alternatives Considered

- **A grep in CI.** Rejected. The survey that led to this ADR counted
  imports with a grep and missed the five relative imports in
  `get_job_service.py`.
- **An import linting package.** Rejected for now. It adds a
  dependency, and the two exceptions would still be code in this
  repository. Revisit it if the rules outgrow one test file.
- **A readiness port in the application layer, with a Postgres
  adapter.** Rejected. It mirrors ADR 0078, but it adds a second
  allowlisted port to this test for one function, and the composition
  root already holds the pool and may import its library.
