# ADR 0061: Prove the Hardening Checks Can Fail

## Status

Accepted. Resolves the first Follow-up named in ADR 0060, except
for the write check, which was verified in a weaker way described
below.

## Context

ADR 0060 added a workflow that asserts the container hardening
properties on every push and pull request. A check that has only
ever passed has not been shown to catch anything, and ADR 0060
recorded that only one of its checks, the shutdown timing, had been
seen to fail.

## Decision

Break each property on a throwaway branch, dispatch the workflow on
that branch, and read which step fails. One branch per property,
because the job stops at the first failing step and a combined break
would hide which check caught what. Every branch was deleted after
its run and never merged.

| Property removed | Failing step | Message |
|---|---|---|
| `exec` in the `CMD` | SIGTERM reaches uvicorn | `docker stop took 10207 ms, SIGTERM is not reaching the app` |
| `USER 10001` | App runs as uid 10001 | `app runs as uid 0, expected 10001` |
| `read_only: true` | Container is read-only | `ReadonlyRootfs is false` |
| `cap_drop: [ALL]` | Container is read-only | `CapDrop is null` |
| `no-new-privileges` | Container is read-only | `SecurityOpt is null` |
| the `:?` requirement on `POSTGRES_PASSWORD` | Compose refuses to start without POSTGRES_PASSWORD | `compose accepted a missing POSTGRES_PASSWORD` |

In every run the steps before the failing one passed and the steps
after it were skipped, so no check masked another.

Two observations from the runs:

- With `cap_drop` removed, the uid and effective capability check
  still passed. A non-root process holds no effective capabilities
  even when Docker's default capability set is available to the
  container, so that check alone cannot catch a missing `cap_drop`.
  The inspect check in the next step is what catches it.
- Removing the password requirement fails the first custom step in
  under a second, before anything is built.

## Evidence for the write check

The step that asserts `docker diff` is empty was not broken on a
branch. A write that the read-only root permits is hard to stage
without changing application code, and removing `read_only` is
caught by an earlier step. Instead, the same command was run
against a throwaway container after a file was written: `docker
diff` reported `C /tmp` and `A /tmp/probe`, and the workflow step
fails on any non-empty output. This shows the command detects
writes. It does not show the workflow step going red.

## Consequences

- Six of the seven checked properties have been shown to fail the
  real workflow on a deliberate break. The seventh, the `docker
  diff` write check, has been verified only at the level of the
  command it runs.
- The runs were dispatched with `workflow_dispatch` on branches.
  They show the workflow can fail. They do not cover a pull
  request trigger.
- The checks cover the app container. Postgres has no equivalent
  restrictions or assertions.

## Alternatives Considered

**Break all properties on one branch.** Rejected: the job stops at
the first failure, so one run would prove one check and hide the
rest.

**Invent an application change that writes to a permitted path to
fail the write check.** Rejected for now: it adds a fake code path
to the repository's history to test a check that is already
guarded by the read-only assertion.

## Follow-ups

- Stage a real write that the read-only root permits, for example a
  tmpfs mount that the app writes to, and confirm the write check
  goes red.
- Open a throwaway pull request, not a dispatch, to confirm the
  workflow also fails on the `pull_request` trigger.
- Still open from ADR 0059 and ADR 0060: a row insert through the
  API on SQLite, a root-owned bind mount for `/data`, the same
  restrictions on Postgres, a secrets file for the database
  password, a Python 3.12 entry in the CI matrix, and running the
  e2e job on frontend dependency updates.
