# ADR 0062: Status of the Hardening Follow-ups

## Status

Accepted. Records the outcome of the follow-ups named in ADR 0058,
ADR 0059, ADR 0060 and ADR 0061. It opens no follow-ups of its own:
every item that is still open stays in the ADR that names it.

## Context

ADR 0058 to ADR 0061 each ended with follow-ups, and later ADRs
restated earlier ones. After the work that followed them, the same
item could be listed as open in one ADR and done in practice. This
ADR is the single place that says which is which, so a reader does
not have to reconcile four lists. Earlier ADRs are not edited. Each
was accurate when it was accepted.

## Resolved

| Follow-up | Named in | Resolved by | Evidence |
|---|---|---|---|
| Read-only root, `cap_drop: [ALL]`, `no-new-privileges` | ADR 0058 | #282, ADR 0059 | Recorded in ADR 0059 |
| A CI job asserting the hardening properties | ADR 0059 | #283, ADR 0060 | Recorded in ADR 0060 |
| A refresh process for the pinned digests | ADR 0058 | #285, ADR 0060 | Dependabot opened pull requests across all six update streams |
| A Python 3.12 entry in the CI matrix | ADR 0058, ADR 0060 | #302 | `test (3.11)` and `test (3.12)` both passed on the pull request |
| A row insert on the SQLite backend | ADR 0059, ADR 0060 | #301 | See below |
| A root-owned bind mount for `/data` | ADR 0059, ADR 0060 | #301 | See below |
| Prove the hardening checks can fail | ADR 0060, ADR 0061 | ADR 0061 and the runs below | See below |
| Review the action bumps against the Node.js 20 notice | ADR 0060 | #289 | See below |

**SQLite.** As uid 10001 with a read-only root, `--cap-drop=ALL` and
`no-new-privileges`, a node was saved and read back through the
SQLite repository on a fresh named volume, and `/data` held only
`neuromesh.db`. The write went through the repository class, not an
HTTP request, so the API server on SQLite has not been started with
a real request. With `/data` bind-mounted from a root-owned host
directory, startup failed at once with `sqlite3.OperationalError:
unable to open database file`. The remedy, giving the directory to
uid 10001, is in the README.

**The hardening checks.** ADR 0061 recorded six of the seven checked
properties failing the real workflow on a deliberate break, and the
seventh, the `docker diff` write check, verified only at the level
of the command it runs. That was accurate when written. The seventh
was later broken with a `tmpfs` mount on a throwaway branch and the
workflow failed on that step with `unexpected writes to the
container filesystem`. All seven have now failed the real workflow.
Separately, a throwaway draft pull request (#300) with `exec`
removed failed the stop-timing step on the `pull_request` trigger,
so the gate also goes red on that event and not only on
`workflow_dispatch`. Both branches were deleted and nothing was
merged.

One property of the write check came out of that run. The mount
point of a `tmpfs` or a volume appears in `docker diff`, so the
check fails on any such mount even before the app writes to it. It
would need an allowlist if a legitimate mount is ever added.

**The Node.js notice.** The deprecation annotation for
`actions/checkout@v4` was raised against ADR 0060. After the actions
group update (#289), the workflows use `checkout@v7`, and the latest
`container-hardening` run on `main` carries no Node.js deprecation
annotation. That run exercises `checkout` and does not use
`setup-python` or `setup-node`, so it covers the action the notice
named and no others.

## Still open

These stay in the ADR that names them. This ADR adds no entry.

- A secrets file for the database password: see
  [ADR 0058](0058-harden-container-defaults-and-keep-credentials-out-of-the-repo.md).
- The same restrictions on the Postgres service: see
  [ADR 0059](0059-run-the-app-container-read-only-with-no-capabilities.md).
- Running the e2e job on frontend dependency updates: see
  [ADR 0060](0060-enforce-container-hardening-in-ci-and-keep-pins-fresh.md).

## Consequences

- A reader who wants the current state of the hardening work reads
  this ADR and follows the three links. The earlier ADRs keep their
  original follow-up lists, which are now partly out of date, and
  this ADR is what says so.
- The table is a record as of its date. A later change that
  resolves one of the three open items belongs in a new ADR, not in
  an edit here.
