# ADR 0058: Harden the Container Defaults and Keep Credentials Out of the Repository

## Status

Accepted.

## Context

Before this change, the container and compose setup carried defaults
that were fine on a laptop and wrong for anything a third party
would review or run:

- The image ran as root.
- `docker-compose.yml` hardcoded the Postgres password as
  `neuromesh`, in two places, and published both the API port and
  the Postgres port on every host interface.
- The image's `CMD` was shell form, so `/bin/sh` was PID 1 and
  uvicorn ran as its child. `docker stop` sent SIGTERM to the shell,
  which did not forward it, so every stop waited out the full 10
  second grace period and ended in SIGKILL. Uvicorn's lifespan
  teardown, which closes the database pool, never ran.
- Seven Postgres test files each carried their own default URL with
  the same hardcoded password, and the wrong port for compose.
- The test suite could be pointed at any database. The presentation
  fixtures run `TRUNCATE ... CASCADE` on the app's pool.

## Decision

**Run as a non-root user.** The image creates a system user and
group with a fixed numeric id (10001), owns `/data` with it, and
switches with a numeric `USER 10001`. A numeric id lets an
orchestrator verify non-root without resolving names.

**Require the database password from the environment.** Compose
reads `POSTGRES_PASSWORD` from `.env`, which is gitignored and
excluded from the Docker build context, and refuses to start with a
message naming the variable when it is unset. `.env.example` is
committed with a placeholder. The password is interpolated into a
connection URL, so it must not contain URL-reserved characters;
generating it with `openssl rand -hex 24` satisfies that.

**Bind published ports to 127.0.0.1.** Both the API and Postgres
are reachable from the host only. Exposing either beyond localhost
becomes a deliberate edit, ideally behind a TLS-terminating reverse
proxy.

**Make uvicorn PID 1.** `CMD exec uvicorn ...` keeps the shell form,
so `${PORT:-8000}` still expands, and replaces the shell with the
server. Measured on this setup: `docker stop` went from 10.5 seconds
to 0.9 seconds, and the log now shows "Shutting down", "Waiting for
application shutdown" and "Application shutdown complete".

**Pin base images by digest.** The Python image was already pinned.
The Postgres image is now `postgres:16-alpine@sha256:...`, keeping
the tag for readability.

**Guard the test database.** A shared session fixture in
`tests/conftest.py` reads `NEUROMESH_TEST_DATABASE_URL`, fails
immediately with one readable message when it is unset, and refuses
any database whose name does not end in `_test`, regardless of
storage backend. A module-level guard in the same file covers the
app's own pool when the backend is Postgres. The seven per-file
default URLs are removed. CI sets the variable explicitly.

## Consequences

- An existing Postgres volume keeps the password it was initialised
  with, because the image only reads `POSTGRES_PASSWORD` into an
  empty data directory. After this change such a volume must be
  reset (`docker compose down -v`) or rotated with `ALTER USER`.
  Rotating the password also invalidates any shell or dotfile that
  exports a URL containing the old one. This happened while making
  this change: a stale `NEUROMESH_TEST_DATABASE_URL` in a shell
  profile made every Postgres test fail authentication until it was
  rebuilt from `.env`.
- Running the Postgres tests now requires setting
  `NEUROMESH_TEST_DATABASE_URL` and creating a `_test` database with
  the schema loaded. This is documented in the README.
- A non-root user cannot bind ports below 1024, so `PORT=80` no
  longer works inside the container.
- The previous hardcoded password remains in git history. It was a
  development credential and is not used elsewhere.
- The CI workflow's database credentials belong to ephemeral service
  containers that exist for one job. A comment at the top of the
  workflow says so.

## Alternatives Considered

**Keep a default development password and print a warning.**
Rejected: a default that works silently is the failure mode being
removed. Failing at `docker compose up` with a message naming the
variable costs one command and cannot be missed.

**Docker or Compose secrets (`POSTGRES_PASSWORD_FILE`).** Deferred,
not rejected. The application reads its connection URL from an
environment variable, so this needs an application change as well as
a compose change, and the URL embeds the password. Recorded below.

**`init: true` (tini) instead of `exec`.** Would also forward
signals, but adds a process and a runtime flag every consumer of the
image would have to know to set. `exec` fixes it inside the image.

**Default every shell to a test URL, or skip Postgres tests when it
is unset.** Rejected: skipping would keep the suite green while
silently dropping the lease-fencing and repository contract tests
that matter most. A loud, immediate failure is the intended
behaviour.

## Follow-ups

- Run the container with a read-only root filesystem and all
  capabilities dropped (`read_only`, `cap_drop: [ALL]`,
  `no-new-privileges`, tmpfs for writable paths). Not applied here
  and not yet tested against the application.
- Verify the standalone SQLite path under the non-root user,
  including a bind-mounted `/data` that is owned by root on the
  host. Only the compose and Postgres path was exercised.
- Move the database password to a secrets file, which requires the
  application to read the URL or password from a file.
- Document a refresh process for the pinned digests so they do not
  go stale, or automate it with Dependabot or Renovate.
- CI runs Python 3.11, matching the image, while local development
  has been on 3.12. A 3.12 matrix entry would close that gap.
