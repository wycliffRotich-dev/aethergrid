# ADR 0102: Read the Public Demo Through a Port of Its Own

## Status

Proposed.

Related: ADR 0064, ADR 0082, ADR 0094, ADR 0097, ADR 0098 and ADR 0099.

## Context

ADR 0094, decision 7, says the public app reads through the existing
application services and repository interfaces. That cannot be built:

- The repositories select from base tables and scope by a tenant
  argument. The public role has no privilege on any base table (ADR
  0097), and the five public views carry no tenant column (ADR 0098).
- The layer rules (ADR 0082) let presentation import infrastructure only
  in the composition root, allow psycopg_pool only there and in
  infrastructure, and allow one entry point that imports only
  app.presentation.api. They have no place for a second app.
- resolve_database_password reads the NEUROMESH_ names, and the public
  settings forbid any fallback to them (ADR 0094).
- PublicSettings still requires AETHERGRID_PUBLIC_TENANT_ID, but ADR 0098,
  decision 6, moved the tenant into public_demo_scope. The app cannot read
  that table, so the setting and the database can disagree and nothing
  would notice.

## Decision

1. One port, app/application/public_read_port.py: a read-only protocol
   with one method per public view (nodes, jobs, workers, leases, events)
   and one frozen record type per view with exactly the view's columns.
   No method takes a tenant. Every method takes a limit, and the reader
   clamps it to a fixed maximum. Every read has a fixed order, and events
   come newest first.
2. A Postgres reader in app/infrastructure/public_read/ implements the
   port. It selects from the five public_* views and from nothing else. A
   test fails if any query in the package names another relation.
3. A function in the same package opens the pool from plain values, a URL
   and a password file path, so infrastructure never imports presentation
   settings. The pool has min_size 1, max_size 5, timeout 2.0 seconds,
   autocommit, and connection options statement_timeout 2000 ms and
   default_transaction_read_only on. The role cannot write anyway, so the
   options are a second barrier and bound a slow query. The timeout is
   the 2 seconds of /health (ADR 0046), not the 5 seconds of the private
   pool (ADR 0051), because an anonymous caller should not hold a thread
   longer than a probe does.
4. The password is read by a shared helper, read_password_file(path,
   setting), extracted from database_credentials.py. resolve_database_password
   calls it and its messages do not change. The public side passes its own
   setting name, so a public error never names a NEUROMESH_ variable.
5. Routes depend on the port. No application service is added until a rule
   needs one, because a pass-through would remove no complexity. The
   public import allowlist gets this one module and nothing else.
6. app/public_main.py is a second entry point that imports only
   app.presentation.public.composition. That module is a second
   composition root: it reads the environment, opens the pool, builds the
   reader and hands it to create_public_app. It may import infrastructure
   and may not import psycopg_pool. The layer test turns its single
   ENTRY_POINT and COMPOSITION_ROOT into tables, and PORTS_IMPLEMENTED
   gains the port module. Each new row comes with a case that must be
   refused.
7. When the reader fails, a route returns 503 with a fixed body. The
   response never carries an exception class or message.
8. AETHERGRID_PUBLIC_TENANT_ID is removed. The tenant lives only in
   public_demo_scope, set by scripts/set_public_demo_tenant.sql. This
   records that ADR 0098, decision 6, replaced ADR 0094, decision 5, and
   that this ADR replaces decision 7.
9. Public responses name allocation, not use. The views hold capacity and
   available, so a bar shows the allocated share, capacity minus
   available. No field or label says usage or utilization.
10. Reads in flight are capped. The limiter of ADR 0103 bounds the rate
    of requests and not the number that run at once, and a route that
    waits on the database holds a server thread. The public app lets
    MAX_READS_IN_FLIGHT reads run at once, 20, and answers a read past
    that at once with the fixed 503 of decision 7, without asking the
    port. The health route does not use a thread. The value is a first
    choice and is not measured.

## Consequences

- The domain gains nothing, as ADR 0094 requires, and the private app and
  its ADR 0064 tests are untouched.
- The layer test is looser in two named places, a second entry point and a
  second composition root, and tighter in one: the public root may not
  import psycopg_pool.
- The public settings tests change on purpose, because of decision 8.
- A new public field is a view migration, a record field, a schema field
  and a test.
- The public app has its rate limiter (ADR 0103), and nothing is deployed
  yet (ADR 0094).

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That the pool values are right. They are first values, to be measured.

## Alternatives Considered

- **Repositories with a tenant argument and grants on base tables.**
  Rejected. ADR 0098 rejected base table grants.
- **The port in domain/repositories.** Rejected. A read model of views is
  not an aggregate repository, and ADR 0094 says the domain gains nothing.
- **A new application subpackage.** Rejected. scheduler_leadership is the
  precedent: one module, named in PORTS_IMPLEMENTED.
- **Presentation queries the views with psycopg.** Rejected. The layer
  rules refuse it, and a route could not be tested without a database.
- **Reuse the private pool and credential reader.** Rejected. It reads the
  NEUROMESH_ names, which ADR 0094 forbids falling back to, and a shared
  pool would put the public app on the private connections.
- **Keep the tenant setting and compare it with the database.** Rejected.
  The app cannot read public_demo_scope, so only an operator script could
  compare them, and a value that nothing consumes can only mislead.

## Progress

2026-11-17. Decision 4 is built: read_password_file in
database_credentials.py (PR 526), with the private messages pinned before
the refactor.

2026-11-17. Decision 8 is built: the tenant setting is gone from the public
settings, and a stale value of the old variable, valid, malformed or empty,
changes nothing. Putting the field back, or requiring the variable again,
failed the new tests. Decisions 1 to 3, 5 to 7 and 9 are not built.

2026-11-19. Decision 1 is built: app/application/public_read_port.py holds
the read-only port and one frozen record per view. Tests pin each record
to the columns of its view in migration 0007, the nullable columns as
optional, no tenant parameter on any method, and no field named for a
private column or for usage. The clamp and the order are the reader's
job and belong to decision 2. Decisions 2, 3, 5 to 7 and 9 are not built.

2026-11-19. Decision 2 is built: app/infrastructure/public_read/ holds
the Postgres reader. Its five queries are fixed strings, and a test reads
the source of the package and refuses any other shape: a base table, a
join, a star, a literal limit or a query built from text. A limit that
is not an integer, a bool included, raises TypeError, and one below 1
raises ValueError, both before the pool is used. A larger limit is cut
to MAX_LIMIT, which is read at each call. Every read has its fixed order
with the id last. The database tests run as the real read role. Removing
an ORDER BY, removing the clamp, copying MAX_LIMIT at import time and
pointing a query at a base table each turned tests red. Each time the
file was restored and its hash compared. Decisions 3, 5 to 7 and 9 are
not built.


2026-11-21. The allowlist half of decision 5 is enforced. The text of
decision 5 says one module. The public app already imports the rate
limiter of ADR 0103, so the allowlist holds two, public_rate_limiter and
public_read_port, and this entry corrects the count without changing the
decision. The import boundary test of ADR 0094 matches them by exact
module name. Any other module under app.application is refused, among
them scheduler_leadership and a near miss named public_read_port_extra,
and so is a bare import of app.application. The prefixes
app.infrastructure.repositories and
app.infrastructure.database_credentials are forbidden. Eleven mutations
of the scan and of the constants were tried. Ten turned tests red: a gate
that accepts every module, a prefix match without the dot, the wrong path
segment, each forbidden prefix removed, each allowed module removed and a
refused module added. One survived at first: the scan of the real package
could stop passing the allowlist and stay green, because that package is
flat and clean. A test that scans a temporary directory with a top level
file and a nested file closed it, and five mutations of the shared scan
helper then turned that test red. Each time the file was restored and its
hash compared. What the tests do not show: the scan reads source text, so
an import made through importlib is not seen by it. The layer test flags
__import__ and import_module calls in every file under app, the public
package included. Nothing here shows what the deployed app can reach at
run time. public_read_port is on the list before anything imports it.
The routes of decision 5 and decisions 6, 7 and 9 are not built.

2026-11-21. Decision 6 is built except the reader. app/public_main.py
imports only app.presentation.public.composition, and importing it opens
nothing. create_app in that module reads the environment, builds the
public settings, opens the pool through open_public_pool with the name of
the public password setting, and gives create_public_app a lifespan that
closes the pool once when the app stops. A bad setting stops construction
before the pool opens, a pool that fails to open passes its fixed error
on, and a failure after the pool opened closes it and re-raises.
create_public_app only forwards the lifespan and never learns what a pool
is. The reader is not built here, because no route uses it. It arrives
with the first route, and decision 6 is not complete until then.

The layer rule is narrower than decision 6, which only forbids
psycopg_pool in the public root. The layer test now holds two tables.
ENTRY_POINTS maps each entry file to the one module it may import, matched
exactly. COMPOSITION_ROOTS maps each root to an infrastructure prefix,
matched with the dot. The public root may import only
app.infrastructure.public_read modules, so psycopg_pool, psycopg, a
private repository, the credential reader and a bare app.infrastructure
are all refused. Because it cannot name ConnectionPool, it types the pool
with a small Protocol that has close. Each new row comes with a refused
case. Thirteen mutations of the tables each turned the predicted tests
red, and two of them showed a gap in the exact match of the entry rule,
which was then closed.

Seven mutations of the composition code, each with the file restored and
its hash compared, turned the predicted tests red and no others: dropping
the close, closing twice, closing at construction, skipping the close
after a construction failure, a wrong setting name, reading the
environment at import time and not passing the lifespan on. A test
against the real database logs in as aethergrid_public_app, enters and
leaves the lifespan and checks that the pool is closed only after it. It
skips without psql. Dropping the close and closing before the yield each
turned it red.

A pool that fails to close when the app stops is not hidden: the error
leaves the lifespan. A close that fails after a construction failure is
suppressed, so the error that stopped construction is the one raised.
Removing that suppression and making the lifespan swallow the close error
each turned the matching test red. A test starts the real command,
uvicorn app.public_main:create_app --factory, as a separate process with a
password file that does not exist. The process exits with a non-zero code
and the fixed message of read_password_file, no server starts and the
database host does not appear in the output. A wrong setting name turned
it red. It needs no database.

The guards test of the public package held its own forbidden list, four
entries against seven in the import boundary test, and a scan that read
only the module of each import and matched without the dot. Both tests
now read one list, FORBIDDEN_PREFIXES in tests/support/import_boundary.py,
and the guards test uses the shared scan. Emptying the list in the guards
test survived at first, because the real package is clean and nothing fed
the check a bad import. The check is now a function with a test that feeds
it a listed prefix and a near miss, and emptying the list and removing the
dot each turned that test red.

Nothing here shows what a deployed app can reach at run time. Not
claimed: safe to expose.

2026-11-21. Correction. Earlier entries that list decision 3 as not built
are out of date. Decision 3 was built by ADR 0104. The entry above that
says decisions 6, 7 and 9 are not built is out of date in one part:
decision 6 is built except the reader. Those lines are left as written.

2026-11-21. Decisions 5, 7 and 9 are built, decision 6 is complete and
decision 10 is added. create_public_app takes the reader and serves five
GET routes next to /healthz: /public/nodes, /public/jobs, /public/workers,
/public/leases and /public/events. Each route asks the port for ROW_LIMIT
rows, 100, and returns a list of a public model. The models are in
app/presentation/public/responses.py. Their fields equal the port records
in order, and the module imports nothing from app.presentation.schemas. A
node also carries allocated_cpu_cores, allocated_memory_mib and
allocated_vram_mib, which are capacity minus available, and an available
amount above capacity is refused. No field or text says usage or
utilization. The composition root builds the reader from the pool and
hands it to create_public_app, which completes decision 6.

When the read, or the mapping of its rows, raises an Exception, the route
returns 503 with the fixed body {"error":"unavailable"} and the failure
goes to the log. A stop signal or a cancellation is not caught. A 503
carries content-length, content-type, vary and, when the request has an
Origin, access-control-allow-origin, and a test pins that set for each
route and keeps the failure text out of every header value. ROW_LIMIT is a
request. The clamp of the reader to MAX_LIMIT is what bounds the rows, and
a test seeds MAX_LIMIT plus 5 rows and shows that each route returns
exactly 100, even with ROW_LIMIT patched to 10000.

Decision 10 came from a test. With 40 reads held in the reader, the health
route waited behind them, because every route was a plain function and
shared the server threads. The health route is now async def, and a gate
of MAX_READS_IN_FLIGHT reads, one for each app, refuses a read past the
cap at once. Tests run every request in one event loop, because the thread
limiter belongs to the loop. They show that the 21st read gets the fixed
503, that the cap frees when the reads end, that the health route answers
with every thread held even when the cap is patched to 1000, that the cap
leaves threads free, and that each app has a cap of its own.

The two guard tests that ADR 0094 listed as not written now exist in
tests/presentation/public/test_public_app_guards.py: every route is rate
limited, and every response model is a public schema. Each comes with an
app that breaks the rule, so the helper is shown able to fail. The public
root cannot import psycopg_pool, so it types the pool with a Protocol, and
a test requires the real pool to have each method of that Protocol.

Forty-three tests cover the response models, and fifteen mutations of them
were killed. Eleven mutations of the routes were tried against a fake
reader: the row limit, an except that names ValueError, an except that
names BaseException, status 500, the body, the log call, the wrong model,
the wrong reader method, the limiter removed, a sixth route and a route
missing from the test table. Ten turned tests red at first. The except on
BaseException survived, because nothing sent a stop signal, and tests that
raise one now close it. Against the real database, as
aethergrid_public_app, five more turned tests red: the reader clamp
removed, an except that names ValueError, a lifespan that closes the pool
with a wrong call, the nodes route reading jobs, and a 503 body that names
the exception class. Raising ROW_LIMIT to 100000 stays green by design,
because the clamp is the guard. Five mutations of the cap turned tests
red: a gate that is never released, a cap of 1000, a plain def health
route, one gate shared by every app and a gate that blocks. Two survived
at first, the plain def and the shared gate, and three tests closed them.
Renaming the close call turned six tests red, two of them the Protocol
tests. A server header, an x-error header and a vary header that holds the
failure text each turned the header test red. Each time the file was
restored and its hash compared.

The real database tests check that each route returns only the scoped
rows, that the JSON equals the model of the records of the reader, and
that no tenant_id, command, labels or payload key appears at any depth. A
closed pool, a revoked grant and an exhausted pool each give the fixed
503, and the pool recovers after the exhaustion. For those three failures
the password, the URL string and the path of the password file appear in
no response and no log, and a test shows that this check can fail.

Nothing here shows what a deployed app can reach at run time. Not
claimed: safe to expose.

2026-11-21. Correction. Earlier entries that say the reader or the routes
are not built, among them the allowlist entry that ends with the routes of
decision 5 and decisions 6, 7 and 9 not built, and the entry that says
decision 6 is built except the reader, are out of date. Those lines are
left as written.

## How to Verify

    pytest -q tests/architecture tests/presentation/public
