# ADR 0017: Starlette TestClient Deprecation Warning

## Status

Accepted

## Context

While introducing API integration tests for the AetherGrid presentation layer, the test suite reports the following warning:

```
StarletteDeprecationWarning:
Using `httpx` with `starlette.testclient` is deprecated;
install `httpx2` instead.
```

The warning originates from:

```
.venv/lib/python3.12/site-packages/fastapi/testclient.py
```

and not from any source file within the AetherGrid project.

## Decision

No code changes will be made within AetherGrid to suppress or bypass this warning.

The project will continue using the officially supported FastAPI `TestClient` implementation until the FastAPI/Starlette ecosystem fully adopts the new testing interface.

No modifications will be made to third-party packages installed inside the virtual environment.

## Consequences

- AetherGrid source code remains warning-free.
- The warning is acknowledged as an upstream dependency deprecation.
- Future dependency upgrades will revisit this decision.
- No vendor code is modified, ensuring clean and reproducible environments.

## References

- FastAPI TestClient documentation
- Starlette release notes regarding `httpx2`
