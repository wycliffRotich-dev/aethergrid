# ADR 0051: Bound the Shared Connection Pool's Timeout

## Status

Accepted

## Context

`_build_repositories()` (`dependencies.py`) constructs the single
`ConnectionPool` shared by every Postgres repository in this
application without passing `timeout`. `psycopg_pool.ConnectionPool`'s
own default for that parameter, confirmed directly against the
installed version via `inspect.signature(ConnectionPool.__init__)`,
is 30.0 seconds. Nothing in this codebase chose that number; it was
inherited silently.

ADR 0046 already discovered this default once, when it was too slow
for `/health`, and routed around it with a 2-second, per-call override
on that one endpoint alone. The override was scoped to `/health`
because at the time nothing else appeared to need it. ADR 0050 proved
that assumption wrong: `ReconciliationLoop.execute()`, threaded off
the event loop specifically so a slow call could no longer freeze the
server, still inherited the pool's 30-second patience on every
repository call it made. Reproduced directly against a stopped
`postgres` container: a reconciliation pass logged

    psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec

confirming the exact number in production log output, not just in the
library's default signature.

This is not an isolated defect in reconciliation. Every Postgres
repository in the application (`PostgresJobRepository`,
`PostgresNodeRepository`, `PostgresWorkerRepository`,
`PostgresEventRepository`, `PostgresLeaseRepository`,
`PostgresApiKeyRepository`) shares this one pool and therefore this
one silent default. Any synchronous route or background call that
reaches one of them during an outage waits up to 30 seconds before
failing, whether or not that wait was ever a deliberate design choice
for that call site. This is the concrete mechanism behind the
thread-pool exhaustion risk named as a follow-up to ADR 0050: each
such call holds a worker thread for the full wait, and enough
concurrent calls during a sustained outage can exhaust the default
thread pool.

## Decision

The shared pool now passes `timeout=5.0` explicitly at construction.

5.0 seconds, not `/health`'s 2.0 seconds: `/health`'s timeout is tuned
for a check whose only purpose is reporting bad news as fast as
possible, with nothing behind it to lose. The shared pool serves every
other repository call in the application, including ones a caller may
be relying on to eventually succeed rather than fail fast; 5 seconds
gives real traffic meaningfully more patience than a bare health probe
while remaining an order of magnitude below the library's 30-second
default, and nowhere near a duration any caller should be expected to
block on.

Verified in two stages. First, isolated: `ConnectionPool` constructed
against a reserved, non-routable address (`192.0.2.1`, TEST-NET-1),
with no `timeout` passed, measured at 30.36s; the same construction
with `timeout=5.0` measured at 5.0s (both within a 2s tolerance,
`tests/infrastructure/test_connection_pool_timeout.py`). Second,
against a real outage: with the fix in place, the same reconciliation
failure that previously logged "after 30.00 sec" now logs

    psycopg_pool.PoolTimeout: couldn't get a connection after 5.00 sec

reproduced twice in one outage window, confirming the fix holds under
production code paths, not only the isolated construction test.

## Consequences

### Positive

- Every caller sharing the pool, not only `/health`, now fails fast
  during an outage instead of inheriting an unexamined 30-second
  default. This directly narrows the thread-pool exhaustion exposure
  named as a follow-up to ADR 0050: each blocked call now holds a
  worker thread for at most 5 seconds instead of 30, a 6x reduction in
  the worst case per call.
- The 30-second default is no longer implicit. A number this
  consequential, one that previously surfaced only as a stack trace
  during a real outage, is now a single explicit keyword argument with
  a comment explaining why 5.0 and not 30.0 or 2.0.
- No schema, retry, or business-logic change. Like ADR 0032 and ADR
  0050, this is purely a timeout value at the infrastructure boundary.

### Negative

- A genuinely slow but eventually successful connection attempt, one
  that previously succeeded somewhere between 5 and 30 seconds, now
  fails instead. This is the deliberate trade this ADR makes: no
  caller in this application should be waiting 30 seconds for a
  connection in the first place, and a caller that needs more patience
  than 5 seconds should retry explicitly rather than rely on this
  pool's default absorbing the wait.
- Reconnection attempts during an outage now happen roughly six times
  as often per unit of wall-clock time (every 5 seconds instead of
  every 30), which correspondingly increases the volume of `WARNING`
  level `error connecting in 'pool-1'` log lines and `ERROR` level tick
  and reconciliation failures during any sustained outage. Confirmed
  directly: a single 15-second outage window that previously produced
  one logged failure now produces three. This is log volume, not a
  correctness problem, since every failure is still caught by the
  existing per-phase try/except (ADR 0032) and logged with a full
  traceback rather than propagating.
- Does not address thread-pool exhaustion outright, only narrows it by
  the same factor as the timeout reduction. A sustained outage with
  enough concurrent request volume could still exhaust the default
  thread pool inside 5-second windows rather than 30-second ones.
  Closed as issue #261. A dedicated pass, likely a bounded or
  dedicated executor, remains worth reopening if sustained outages
  in practice turn out frequent enough to matter.
- Does not change recovery latency once the database returns. A
  reproduction spanning a real Postgres restart measured roughly 15
  seconds from `docker compose start postgres` to the first successful
  `/health` response, observed in production logs as Postgres's own
  `FATAL: the database system is starting up`, a startup cost entirely
  external to this application and unaffected by any pool timeout
  chosen here.

## Alternatives Considered

### Leave the 30-second default and rely only on ADR 0050's thread-hop fix

Rejected. ADR 0050 correctly keeps a slow call from freezing the event
loop, but does nothing about how long that call is allowed to run on
its own thread. The two problems are independent: one is about where
a blocking wait happens, the other is about how long it is permitted
to last. Leaving the second unaddressed keeps the exact thread-pool
exhaustion exposure ADR 0050 flagged as a known follow-up, unsolved.

### Give each repository, or each call site, its own timeout

Rejected. `/health` earned a genuinely different value under ADR 0046
because its purpose, and its willingness to sacrifice patience for
speed, is categorically different from a repository serving normal
application traffic. No comparable case exists yet for treating any
of the six Postgres repositories differently from one another; a
single shared value for the shared pool is the simplest design that
fits every current caller, and the pattern established by ADR 0046
already shows how to special-case a future one if it ever needs its
own value.

### Choose 2 seconds, matching `/health`

Rejected. `/health`'s 2 seconds is calibrated for a check with nothing
to lose by failing fast: reporting unhealthy a moment sooner has no
downstream cost. Every other repository caller does have something to
lose: a scheduler tick, a job status update, a lease renewal. 5
seconds keeps the same order-of-magnitude improvement over the
30-second default while giving real work more room to survive a
brief, sub-5-second blip without being penalized as aggressively as a
pure health probe.

### Choose 30 seconds but move every affected call off the event loop instead

Rejected as insufficient on its own. This is what ADR 0050 already
did, and it was necessary, but not sufficient: moving a 30-second wait
off the event loop still leaves it a 30-second wait, still capable of
holding a worker thread for that long, still the mechanism behind
issue #261. Threading and bounding the timeout are complementary
fixes, not substitutes for each other.
