# ADR 0063: Close the Remaining Hardening Follow-ups

## Status

Accepted. Resolves the three items that ADR 0062 left open: running
the e2e job on frontend changes (ADR 0060), the same restrictions on
Postgres (ADR 0059), and a secrets file for the database password
(ADR 0058). It opens no follow-ups of its own.

## Context

ADR 0062 recorded every hardening follow-up from ADR 0058 to ADR
0061 and left three open, each linked to the ADR that named it. All
three have since been done. This ADR records how, with what each
change was checked against.

## Decision

**e2e on frontend changes (#304).** A small `changes` job diffs the
pull request against its base and reports whether it touches
`frontend/` or `ci.yml`. The `e2e` job runs on a pull request when it
does, and keeps its existing triggers, push to `main` and
`workflow_dispatch`. The suite waits out the real 60 second
heartbeat timeout, which is why it was not run on every pull
request, and that reasoning is kept. Both directions were shown on
real pull requests: #304 edits `ci.yml` and `e2e` ran and passed on
it, and #305 touched only `docker-compose.yml`, where `changes`
succeeded and `e2e` was skipped. The push run to `main` after #304
ran all five jobs.

**Postgres hardening (#305).** The `postgres` service runs with
`read_only: true`, `cap_drop: [ALL]` with `CHOWN`, `SETUID`, `SETGID`
and `DAC_READ_SEARCH` added back, `no-new-privileges`, and a tmpfs on
`/var/run/postgresql`. The set was measured against the pinned image,
and each capability was forced by an error:

- With every capability dropped, the entrypoint failed to `chmod` the
  data directory, to write the socket directory, and to switch to the
  `postgres` user.
- `CHOWN` is required: without it the entrypoint's `chown` of the
  socket directory failed and the container exited.
- `SETUID` and `SETGID` are required for the switch to `postgres`.
- `FOWNER` was tried and is not needed. A `chmod` error still
  appears in the log without it and is not fatal.
- `DAC_READ_SEARCH` looked removable on a fresh volume, where the
  container started without it. On a copy of the real data volume
  the entrypoint's `find` failed with `Permission denied` and the
  container did not start, so it stays.

On the real service: healthy after recreate, healthy after `docker
kill` with a 21 second recovery that the 30 second start period
covers, and the rows were intact. `docker diff` on the container
showed only the mount point of the `schema.sql` bind mount, so
nothing is written to the container layer.

**The database password (#306).** The password is no longer an
environment variable or part of a connection URL. Compose passes it
as a Docker secret: Postgres reads `POSTGRES_PASSWORD_FILE`, and the
application reads `NEUROMESH_DATABASE_PASSWORD_FILE` through
`resolve_database_password`, which hands it to the connection as a
keyword. With no file configured the behavior is exactly what it was.
A password in both the URL and the file is a startup error that names
both settings, and an unreadable or empty file is an error that names
the path and never the contents. The helper has seven tests, and the
full suite passed with the password only in the file, then again in
the old mode with it in the URL.

Checked on the running stack: neither container's environment
contains a password or a `user:password@` URL, `docker compose
config` contains no trace of the value, the existing database
accepted the password through the file, and the app logged no
authentication failures. A first attempt failed in the way the
helper is meant to report: the app refused to start with `Permission
denied` on the secret, because a file secret keeps the host file's
owner and the container runs as uid 10001. The remedy, `chown
10001:10001` on the file, is in the README.

**Checks that follow.** The hardening workflow's first check used to
assert that compose refuses to render without `POSTGRES_PASSWORD`.
That guard no longer exists. Compose does not validate a missing
secret file at `config` time, but `up --no-start postgres` fails
with `invalid mount config for type "bind": bind source path does
not exist`, so the check now asserts that. The next step generates
the secret file, owns it to uid 10001, and starts the stack.

## What a clean clone found

Following only the README on a fresh clone and a fresh volume, the
stack came up healthy and a key was issued through the password file.
It also exposed a fault: Postgres exited with `schema.sql: Permission
denied`, because a restrictive umask checked the file out unreadable
to the container's `postgres` user. The README now makes the file
readable before compose starts (#308).

## Consequences

- The write check in the hardening workflow inspects the app
  container only. The `postgres` container's `docker diff` is not
  empty, because the mount point of the `schema.sql` bind mount
  appears in it, so extending that check to Postgres would need an
  allowlist.
- Host-side tools such as the key script and the test suite cannot
  read the container's secret file, which is owned by uid 10001. The
  README has them read a private copy, `secrets/postgres_password.local`,
  which is ignored by git and by the Docker build context.
- The unit tests for the helper and the Postgres contract tests were
  run with the password in a file and none in the URL. The hardening
  workflow's new secret-file steps ran green on `main` for #306.

## Alternatives Considered

**Keep `FOWNER` and `DAC_READ_SEARCH` out on the strength of a fresh
volume test.** Rejected for `DAC_READ_SEARCH`: the fresh volume
passed without it and a copy of the real data did not.

**Make the password a `chmod 644` file.** Rejected for the secret:
any local user could read it. Owning it to uid 10001 with mode 600
keeps it private and matches the user the image already defines.

**Run e2e on every pull request.** Rejected: the job's own comment
records why it does not, and the path filter keeps that cost for the
changes that can break what the suite checks.
