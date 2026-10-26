# ADR 0078: Elect One Scheduler With an Advisory Lock

## Status

Accepted. The cluster tick runs only in the process that holds a
Postgres advisory lock, so a second process on the same database waits
instead of scheduling against the same nodes.

Related: ADR 0021, ADR 0023, ADR 0032 and ADR 0046.

## Context

The cluster loop in `app/presentation/api.py` starts inside the API
process. Once a second it runs a scheduling and execution pass, then a
reconciliation pass. Nothing stopped a second process on the same
database from running its own copy.

Two ordinary events start a second one: a second replica, and a rolling
deploy, where the old and new containers overlap for a few seconds. The
image starts `uvicorn` with no `--workers` flag, so one container runs
one process. That does not cover either event.

A search of `app` found advisory locks only in the migration runner, and
no `FOR UPDATE` or `SKIP LOCKED` anywhere. ADR 0021 and ADR 0023 scope
rate limiting and error tracking to one process. No document said the
scheduler must run once.

The unique constraints on `leases` stop one job from getting two leases
and one worker from holding two. They do not stop two ticks from each
reading the same node as having room and each allocating against it. The
tests run one tick at a time, so none of them could show it.

This was found by review. It was not reproduced.

## Decision

1. A port, `SchedulerLeadership` in
   `app/application/scheduler_leadership.py`, answers one question:
   may this process run the tick now. `try_acquire()` returns a bool and
   never raises for a lost lock or an unreachable database. `release()`
   is safe to call when not leading and safe to call twice.
2. `PostgresSchedulerLeadership` holds a session level advisory lock on
   a dedicated connection that is not part of the pool, because a pooled
   connection returns to the pool and the lock would go with it. The
   connection uses autocommit, so it never sits idle inside a
   transaction, and it must reach Postgres directly, because session
   level locks do not survive a transaction mode pooler.
3. The lock key is `nm_sched`, not the migration key `nm_migra`, so a
   migration run and a scheduler never wait on each other.
4. Each call to `try_acquire()` pings the held connection with
   `SELECT 1`. A failed ping means the lock is gone. The adapter drops
   the connection and tries to take the lock again on a new one.
5. The connection sets a connect timeout of 5 seconds, TCP keepalives
   (30 seconds idle, 10 seconds apart, 3 probes) and a `tcp_user_timeout`
   of 10 seconds. A tick can run a job's command for a long time while
   the lock connection sits idle, and these settings bound how long a
   dead connection goes unnoticed.
6. Losing or regaining the database is logged when the state changes,
   not once per tick.
7. `InMemorySchedulerLeadership` always leads. The sqlite and memory
   backends use it, chosen by the same `_connection_pool is not None`
   test that picks the tenant repository, because neither backend can
   share a database between processes.
8. `_run_leader_tick` in `api.py` asks for leadership on a worker thread,
   skips the tick for a follower, and logs and skips the tick when the
   election itself raises, so an election error cannot end the loop.
   `_run_cluster_loop` releases leadership in a `finally`, so a clean
   shutdown hands it over at once.
9. The password comes from `resolve_database_password`, the same way the
   pool and the migration runner get it.

## Evidence

- Six tests run against a real Postgres: the first process leads and the
  second does not, repeated calls do not stack the lock, a follower takes
  over after a release, a follower takes over after the leader's backend
  is ended with `pg_terminate_backend`, an unreachable database reports
  `False` without raising, and `release()` is safe before any acquire and
  when repeated. They pass.
- Four tests cover the in-memory adapter. Four cover the gate: a follower
  skips the tick, a leader runs it, a failing election skips the tick
  without raising, and a cancelled loop releases exactly once. The
  presentation suite passes (151).
- Four changes to the code were each made and then reverted: the gate
  no longer skips a follower, the adapter ignores the lock result, the
  ping on the held connection is removed, and the loop no longer
  releases leadership. A test failed for every one of them.
- The full suite passes (988), run with no path as CI runs it, so it
  includes the tests under `integrations/resilient_client/`.
  `ruff check .` is clean.
- The existing test that guards pooled connection state passes with the
  new adapter.

## Consequences

- Several processes can share one database. Only one runs the tick at a
  time, including during a rolling deploy.
- A leader that loses its connection learns of it at its next
  `try_acquire()`, once per tick. A tick that is already running, for
  example one executing a job's command (ADR 0028, ADR 0032), finishes
  first. In that window a new leader can start a tick while the old one
  is still running.
- A follower takes over when Postgres ends the leader's session. If the
  process dies, that is immediate. After a network partition it depends
  on the server's TCP keepalive settings, which this change does not set.
- Each process holds one more connection to Postgres, outside the pool.
- The scheduler connection must reach Postgres directly. If a
  transaction mode pooler is ever placed in front of the database, this
  connection must bypass it.

## Not Claimed

- That exactly one scheduler runs at every instant. Leadership narrows
  the window to a failover and does not close it. The unique constraints
  and the tenant checks stay as the backstop.
- That oversubscription was ever observed. This closes a gap found by
  review.
- That the API is safe to run as several replicas. Rate limiting (ADR
  0021) and error tracking (ADR 0023) still keep their state in each
  process, so every replica applies its own limits. That needs its own
  decision before a second replica is run.
- That each of the four changes above failed for the reason it was
  meant to. A test failed each time, and the failure messages were not
  read.
- Any throughput or latency figure. No load test has been run.

## Alternatives Considered

- **State that only one instance may run.** Rejected. It does nothing
  for the overlap during a deploy, a stray container, or a second worker
  process, and nothing would enforce it.
- **A transaction level advisory lock around each tick.** Rejected. A
  tick may run a job's command for an unbounded time, so it would hold a
  transaction open for that long.
- **A row lock on a leader table.** Rejected. It needs a lease with an
  expiry and a renewal path, and the advisory lock already ends when the
  connection does.
- **External election through Redis or a cluster lease.** Rejected. It
  adds a dependency, and Postgres is already required.
