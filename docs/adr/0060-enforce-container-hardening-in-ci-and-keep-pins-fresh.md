# ADR 0060: Enforce Container Hardening in CI and Keep Pins Fresh

## Status

Accepted. Resolves the CI follow-up named in ADR 0059 and the pin
refresh follow-up named in ADR 0058.

## Context

ADR 0058 and ADR 0059 hardened the container: a non-root user,
credentials from the environment, localhost-only ports, `exec` so
uvicorn is PID 1, a read-only root, all capabilities dropped, and
digest-pinned base images. Every property was verified by hand.
Nothing stopped a later change from undoing one, and the pinned
digests and action versions would go stale without anyone noticing.

## Decision

**Assert the properties in CI (#283).** A separate workflow,
`container-hardening.yml`, runs on every push and pull request to
`main`. It generates a throwaway password, starts the compose stack,
and fails if any of these stop holding: compose refuses to render
without `POSTGRES_PASSWORD`; the app runs as uid 10001 with an empty
effective capability set; the container reports a read-only root,
`CapDrop=[ALL]` and `no-new-privileges`; `docker diff` is empty
after a liveness request; and `docker stop` finishes in under 3
seconds with "Application shutdown complete" in the logs. The checks
are written inline in the YAML, because the repository's
`.gitignore` excludes `*.sh` and a helper script would have been
ignored.

**Pin the runners (#284).** All five jobs use `ubuntu-24.04`, not
`ubuntu-latest`, which GitHub announced would begin moving to
Ubuntu 26 on October 19, 2026. The environment now changes in a
pull request, with CI to vet it.

**Add Dependabot (#285).** Weekly updates for the `docker`,
`docker-compose`, `github-actions`, `pip` (two manifests) and `npm`
ecosystems, grouped so that a handful of pull requests arrive, not
one per package. Python minor and major versions and Postgres major
versions are ignored on purpose: the first changes what
`requires-python`, CI and the image agree on, and the second needs a
data migration plan.

**Hold two frontend majors (#293, #295).** The first frontend group
pull request failed at `npm ci`: it moved `typescript` to 7.0.2
while `typescript-eslint@8.71.0` declares a peer range of
`>=4.8.4 <6.1.0`. After that hold, the replacement group failed at
`vite build`: it moved `tailwindcss` from 3.4 to 4.3, and Tailwind 4
moved its PostCSS plugin to `@tailwindcss/postcss`. Both majors are
ignored in `dependabot.yml`, each with a comment saying why, so the
rest of the group can land. Neither install was forced with
`--legacy-peer-deps`.

## Evidence

- The hardening job was proven able to fail for one of its six
  checks. A throwaway branch removed `exec` from the `CMD`, and the
  job failed on the stop-timing step with "docker stop took 10207
  ms, SIGTERM is not reaching the app", after every earlier step
  passed.
- The job runs on Dependabot pull requests. On the Postgres digest
  refresh (#286) and the `httpx` bump (#291), `Container hardening`
  passed in about 40 seconds.
- Dependabot produced pull requests across all six update streams
  within hours of merging, including a digest-only refresh of the
  pinned Postgres image, which shows the `docker-compose` ecosystem
  handles a `tag@sha256` reference.
- After the batch of dependency merges (#286 to #291), the `CI`
  workflow dispatched on `main` passed all three jobs: `test`,
  `frontend` and `e2e`.

## Consequences

- Removing `USER`, `read_only`, `cap_drop`, `no-new-privileges` or
  the password requirement now fails a check. Only the stop-timing
  check has been shown to fail on a deliberately broken change. The
  other five have only seen healthy input.
- The `e2e` job is skipped on Dependabot pull requests, deliberately,
  because it is slow. A frontend update that passes install, lint,
  test and build has therefore not been exercised against the real
  dashboard. The full workflow can be run on the branch through
  `workflow_dispatch` before such a pull request is merged.
- Two held majors need a person to lift them. The `typescript` hold
  ends when `typescript-eslint` supports TypeScript 7. The
  `tailwindcss` hold ends with a Tailwind 4 migration, which also
  changes configuration and utilities and should be checked against
  the e2e suite.
- Dependabot opens many pull requests in its first week and settles
  afterwards. That volume was accepted as is.

## Alternatives Considered

**A helper shell script for the checks.** Rejected: `.gitignore`
excludes `*.sh`.

**Forcing the frontend installs with `--legacy-peer-deps`.**
Rejected: it would pass while running the linter against a
TypeScript major it does not declare support for.

**Installing `@tailwindcss/postcss` to make the Tailwind 4 build
pass.** Rejected as a quick fix. The migration also changes
configuration and utilities, so a passing build could still render
the dashboard differently.

**Letting Dependabot propose Python and Postgres major bumps.**
Rejected for the reasons given above.

## Follow-ups

- Prove the other five hardening assertions can fail, each with its
  own throwaway branch, since the job stops at the first failing
  step.
- Run the e2e job on frontend dependency updates, or document the
  manual dispatch as a merge requirement.
- Exercise a row insert through the API on the SQLite backend, and
  test a root-owned bind mount for `/data`.
- Apply equivalent restrictions to the Postgres service.
- Still open from ADR 0058: a secrets file for the database
  password and a Python 3.12 entry in the CI matrix.
- Review the action version bumps from #289 against the Node.js 20
  deprecation notice that `actions/checkout@v4` triggered.
