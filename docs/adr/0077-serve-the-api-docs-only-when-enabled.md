# ADR 0077: Serve the API Docs Only When Enabled

## Status

Accepted. `/docs`, `/redoc` and `/openapi.json` are off unless
`NEUROMESH_ENABLE_API_DOCS` is set, and a test fails if the framework
adds any route outside the route registry.

Related: ADR 0015, ADR 0064 (point 10) and ADR 0076.

## Context

ADR 0015 and the README say every route requires an API key. A runtime
check showed that was not true. `GET /docs`, `/redoc`, `/openapi.json`
and `/docs/oauth2-redirect` each returned 200 with no credential.
FastAPI adds them itself unless they are switched off, and
`FastAPI(...)` in `app/presentation/api.py` did not switch them off.

The route registry of ADR 0064 did not see them. It takes its paths
from the OpenAPI schema and from the router modules, and these routes
are in neither. The registry exempts exactly three routes, `GET /`,
`GET /health` and `GET /livez`, each with a reason that cites ADR 0064
point 10.

The exposure is reconnaissance, not a breach. A caller with no key could
read every route, request schema and scope name, including the surfaces
gated by `jobs:execute` and `keys:manage`. It reads no data and performs
no action. It does contradict the stated authentication boundary.

## Decision

1. The docs routes are off by default. `docs_url`, `redoc_url` and
   `openapi_url` are `None` unless `NEUROMESH_ENABLE_API_DOCS` is `1`,
   `true` or `yes`, in any case. The flag is for local development.
2. A test asserts that each of the four paths returns 404 by default.
3. A guard test asserts that the app holds no plain `Route`, so a route
   added by the framework or by hand outside `APIRoute` fails the suite
   instead of escaping the registry.
4. The exempt set does not change. The only unauthenticated routes are
   `GET /`, `GET /health` and `GET /livez`.

## Evidence

- With the flag unset, the four paths return 404 and the registry test
  still passes, so `app.openapi()` keeps working in process.
- With the flag set, five of the eleven new tests fail: the four paths
  and the guard. The test can fail.
- The full suite passes (938).

## Consequences

- The Docker image and any deployment read the same app, so the docs
  are dark there too. To keep them, set `NEUROMESH_ENABLE_API_DOCS=1` in
  that environment.
- The flag is read once, at import time. Changing it needs a restart.
- Tools that fetch `/openapi.json` for client generation need the flag.

## Not Claimed

- That every other route returns 401 without a key. The registry
  classifies them and the routers carry the key dependency, but this
  change did not sweep every route at runtime.
- That the exempt probes reveal nothing. On failure `/health` returns
  the class name of the exception, for example `PoolTimeout`. That is a
  separate, smaller question.

## Alternatives Considered

- **Gate the docs behind an API key.** Rejected for now. It needs custom
  routes and more to test, and the pilot does not need public docs.
- **Leave them on and correct the wording.** Rejected. Closing the
  exposure costs less than explaining it to every reviewer.
- **Disable only `/openapi.json`.** Rejected. `/docs` and `/redoc` load
  the schema from it, so they would be broken pages.

2026-10-20. The e2e job in ci.yml used GET /docs as its readiness probe, so it
failed on main after this change, because /docs now answers 404. It probes
GET /health instead, which is exempt (ADR 0064 point 10) and checks that the
database is reachable. A search of .github, compose, the Dockerfile, scripts and
the frontend found no other use of /docs or /openapi.json.
