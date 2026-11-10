# Contributing to AetherGrid

AetherGrid is a distributed AI compute orchestration control plane. Its core
problem is executing workloads reliably when workers fail, state goes stale,
and ownership becomes ambiguous. Contributions are welcome, and the bar is
correctness under failure, not volume.

## Before you start

1. Read the README and run its setup once. CI executes the README setup blocks
   on a clean runner, so what it says works.
2. Skim `docs/adr/`. Many decisions exist because something previously broke
   or was ambiguous. If your change touches leases, reconciliation, worker
   lifecycle, cancellation, authentication, or persistence, find the ADRs that
   cover it first.
3. For anything larger than a small fix, open an issue before writing code so
   we can agree on the problem and the boundary.

Outside contributors work from a fork. Fork the repository on GitHub,
clone your fork, create a branch for the change, and open the pull
request from that branch against `main`.

## Local setup

Requirements: Python 3.11 or 3.12, Docker with Compose, `openssl`.

These steps mirror the README, which CI executes on a clean runner. If they
drift from the README, the README is right.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Create the database password files and start PostgreSQL:

```bash
mkdir -p secrets
openssl rand -hex 24 | tr -d '\n' > secrets/postgres_password
cp secrets/postgres_password secrets/postgres_password.local
chmod 600 secrets/postgres_password secrets/postgres_password.local
sudo chown 10001:10001 secrets/postgres_password
docker compose up -d postgres
```

The test suite runs against a real PostgreSQL database, as CI does. Create an
empty test database and apply the migrations. The database name must end in
`_test`, and pytest refuses to run otherwise:

```bash
docker compose exec -T postgres psql -U neuromesh -d neuromesh -c 'CREATE DATABASE neuromesh_test'
export NEUROMESH_TEST_DATABASE_URL="postgresql://neuromesh@127.0.0.1:5433/neuromesh_test"
export NEUROMESH_STORAGE_BACKEND=postgres
export NEUROMESH_DATABASE_PASSWORD_FILE=./secrets/postgres_password.local
NEUROMESH_DATABASE_URL="$NEUROMESH_TEST_DATABASE_URL" python -m app.infrastructure.migrations
pytest
```

## The checks every change must pass

Setup is done once. Rerun these three before every push. They are the same
commands CI runs, and `pytest` is the full suite. All three must be clean
before you open a pull request, and the whole repository must be clean, not
only the files you touched.

```bash
pytest
ruff check .
mypy
```

Frontend changes, from `frontend/`:

```bash
npm ci
npm run lint
npm run test -- --run
npm run build
```

The browser end-to-end suite runs on merge to `main` and on pull requests that
touch `frontend/`. It deliberately waits out the real worker heartbeat timeout,
so it is not run on every pull request.

## Standards

**Layering.** Dependencies point inward: Domain, Application, Infrastructure,
Presentation. The domain stays pure Python. No ORM models, web framework
imports, or database clients in domain code. The database is an implementation
detail and the API is an interface, not the system.

**Failure first.** For every meaningful change, state in the pull request what
happens when the worker dies, the process dies, a write succeeds but the
response is lost, two workers act at once, or the operation is retried. A
change that only describes the happy path is incomplete.

**Leases and reconciliation are correctness, not housekeeping.** A worker that
has lost its lease must not keep acting as if it owns the job. Recovery must be
safe to run more than once and must not race a healthy worker or a
cancellation. If your change weakens any of these, it needs an ADR and a very
good reason.

**Tests are executable specifications.** Add tests that prove the invariant
and the failure path, including races and persistence behavior where relevant.
Never weaken or delete a test to make a build pass unless the behavior was
intentionally changed, and say so in the pull request.

**No abstraction without a problem.** Explain what complexity an abstraction
removes. Do not add brokers, frameworks, or layers because they are
fashionable.

**Be precise in claims.** Code, docs, and ADRs must not claim exactly-once
execution, cryptographic provenance, consensus, or production scale unless it
is implemented and demonstrated. Prefer "currently implements", "enforces",
"tested through".

**Fix gaps, do not just document them.** If you find a gap you can close, close
it in the same pull request or the next one instead of recording it as a known
limitation.

## Architecture Decision Records

Write a new ADR in `docs/adr/` when a change materially alters the architecture
or establishes a new invariant. Search existing ADRs first and reuse a decision
when one already applies. An ADR records context, the problem, the decision,
alternatives considered, and consequences. Follow the numbering and shape of
the most recent ADRs, and keep any Not Claimed section short. Do not write
em dashes in ADR text.

## Pull requests

- One focused change per pull request, with a message that explains what
  actually changed and why.
- Include the Problem, the evidence, the change, the trade-offs, and the tests.
- Do not rewrite shared history.
- Never commit secrets or real credentials. Report vulnerabilities as described
  in `SECURITY.md`, not in a public issue.

Thank you for helping make AetherGrid more correct and more reliable.
