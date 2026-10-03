# ADR 0059: Run the App Container Read-Only With No Capabilities

## Status

Accepted. Resolves the first Follow-up named in ADR 0058, and
partly resolves the second.

## Context

ADR 0058 moved the app to a non-root user but left the container
able to write anywhere in its own filesystem, with Docker's default
bounding capability set still available to anything that gains
privileges, for example through a setuid binary. ADR 0058 listed a
read-only root filesystem, dropped capabilities and
no-new-privileges as a follow-up, noting they had not been tested
against the application.

## Decision

Add three settings to the `neuromesh` service in
`docker-compose.yml`:

- `read_only: true`
- `cap_drop: [ALL]`
- `security_opt: [no-new-privileges:true]`

No tmpfs is added. The decision to add none rests on measurement:
after startup and after exercising the API, `docker diff` on the
running container listed no written paths, so there was nothing to
give a writable mount.

Verification, all against the compose stack:

- `docker inspect` reports `ReadonlyRootfs=true`,
  `CapDrop=[ALL]` and `SecurityOpt=[no-new-privileges:true]`.
- `touch /app/probe` inside the container fails with "Read-only
  file system".
- `CapPrm` and `CapEff` of PID 1 are both all zeros.
- The container reaches `(healthy)` and its healthcheck keeps
  passing.
- With a scoped key: `POST /nodes`, `POST /jobs` and
  `POST /workers` returned 201, `GET` on `/jobs`, `/nodes`,
  `/workers`, `/events` and `/cluster/health` returned 200, and
  `POST /api-keys/{id}/revoke` returned 204, after which the
  revoked key got 401.
- After 30 further seconds of background loops, the logs held no
  read-only or permission errors, and `docker diff` was empty.

The SQLite backend, which is the image default, was started on its
own with the same three restrictions and a fresh named volume for
`/data`. It reached `Application startup complete`, `/livez`
returned 200, and `neuromesh.db` existed at 28 KB owned by
10001:10001. `/data` was writable by that user, and `docker diff`
showed nothing written outside `/data`.

## Consequences

- These are runtime settings of the compose file, not properties of
  the image. Running the image with plain `docker run`, or under
  another orchestrator, does not inherit them. The Kubernetes
  equivalents are `readOnlyRootFilesystem: true`,
  `capabilities.drop: [ALL]` and
  `allowPrivilegeEscalation: false`.
- Any future code that writes local files, such as temp files,
  caches or uploads, will fail with a read-only error until a tmpfs
  or volume is added on purpose. A new write path becomes a
  deliberate decision, which is the intent.
- The checks cover the API server container. Worker execution runs
  in separate agent processes, so it was outside this
  verification.

## Alternatives Considered

**Add a tmpfs for `/tmp` and other likely paths up front.**
Rejected: it would hide writes the application does not make. The
measured result was that none were needed, and a mount added
speculatively would stop the next accidental write from failing.

**Apply the same restrictions to the Postgres service.** Deferred.
The official image's entrypoint is expected to start as root to
prepare its data directory and to need writable runtime
directories, so it would need tmpfs mounts and some capabilities
added back. That is a separate piece of work and was not tested.

**Rely on the non-root user alone.** Rejected as the end state: it
leaves the filesystem writable and the bounding capability set at
the default, which is what this change narrows.

## Follow-ups

- Exercise a row insert through the API on the SQLite backend. Only
  startup, database creation and file ownership were verified there.
- Test SQLite with a bind-mounted `/data` that is owned by root on
  the host. Only a fresh named volume was tested.
- Apply equivalent restrictions to the Postgres service, expecting
  tmpfs mounts and a reduced set of added capabilities.
- Add a CI job that asserts these properties, so a later change
  cannot undo them unnoticed: uid 10001, a read-only root, empty
  capabilities, `docker stop` finishing in a few seconds, and
  compose refusing to start without `POSTGRES_PASSWORD`.
- Still open from ADR 0058: a secrets file for the database
  password, a refresh process for the pinned digests, and a Python
  3.12 entry in the CI matrix.
