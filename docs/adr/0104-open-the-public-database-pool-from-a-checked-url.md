# ADR 0104: Open the Public Database Pool From a Checked URL

## Status

Proposed.

Related: ADR 0046, ADR 0094, ADR 0097, ADR 0099 and ADR 0102.

## Context

ADR 0102, decision 3, says a function in app/infrastructure/public_read/
opens the pool from a URL and a password file path. It does not say what
the URL may contain, what happens when the database cannot be reached, or
which login the pool may use. Reading the URL the way libpq reads it shows
a flaw in the check that the public settings already make:

- The settings refuse a password by reading the user part of the URL. A
  password written after a question mark passes that check, and libpq
  uses it.
- A fragment passes the same way. libpq reads db#?password=x as the
  database name db# with the password x.
- A key written with a percent escape, such as pass%77ord, is read as
  password. A check on the raw text misses it.
- A user written in the query replaces the user of the URL.
- An options value in the query reaches the connection, so a URL could
  change the session settings that decision 3 sets.
- A key spelled with a capital makes libpq raise an error that can carry
  the URL.

The URL is written by the operator and not by a request, so this is a
configuration risk. It is still a hole in the line that keeps a password
out of the URL, and the pool function should not depend on presentation to
close it.

## Decision

1. One module, app/infrastructure/public_read/public_pool.py, holds
   open_public_pool(database_url, password_file, password_file_setting).
   It takes plain values. The setting name is an argument, so infrastructure
   imports nothing from presentation and a public error never names a
   NEUROMESH_ variable.
2. The URL is parsed by libpq, through psycopg's conninfo_to_dict, so the
   check sees what the connection will use. Only these keys are accepted:
   host, port, dbname, user, sslmode and sslrootcert. Any other key is
   refused, password, passfile, service and options included. A database
   name that contains a hash sign is refused. An error from the parser is
   turned into the same fixed refusal.
3. The user must be aethergrid_public_app (ADR 0099). The pool never logs
   in as the owner or as any other role.
4. The password is read by read_password_file with the setting name that
   was given, and is passed to the pool as a keyword. A password in the URL
   is refused under decision 2.
5. The pool values and the connection options are those of ADR 0102,
   decision 3. The options are set by this function only. A URL cannot
   carry them.
6. The function waits for the first connection. When that fails, it closes
   the pool and raises one fixed message that names the setting. The
   message, the exception chain and the log records never hold the
   password, the URL or the driver's text. A bad password or an unreachable
   database stops the app at start, and the first visitor does not find it.
7. The public settings keep their own URL check as a first fence. It is not
   the boundary, and the function does not rely on it.
8. Each refusal in decisions 2, 3 and 6 has a test that fails when the
   check is removed. A recording stand-in for the pool tests the arguments
   without a database. Tests against the real database log in as
   aethergrid_public_app with its password from a file, read all five views,
   and are refused a base table. A wrong password is refused. The owner's
   PGPASSWORD is removed from the environment in those tests, so it can
   never stand in for the right one.

## Consequences

- The flaw in the settings check is recorded here. The pool function is
  where it is closed.
- A new key in the URL is a decision of this ADR and a test.
- The role has a connection limit of 10 and the pool takes up to 5, so a
  second process of the public app would share what is left.
- The function never touches the network when the URL is refused.

## Not Claimed

- That the public demo is safe to expose. Nothing is deployed.
- That the connection is encrypted. sslmode is the operator's setting.
- That the pool values are right. They are first values, to be measured.

## Alternatives Considered

- **Refuse a list of bad keys.** Rejected. A key that is not on the list
  gets through, and the forms above show how many ways one key can be
  written.
- **Check the URL with urlsplit.** Rejected. It does not read the URL the
  way libpq does, and the fragment and the escape pass it.
- **Let the first request find a bad password.** Rejected. A visitor should
  not be the one who finds it.
- **Allow any user in the URL.** Rejected. A mistake would log the public
  app in as a role with more rights.

## Progress

2026-11-20. Decisions 2 and 3 are built: app/infrastructure/public_read/
public_pool.py checks the URL the way libpq reads it. Only the listed
keys pass, the user must be the public app role, and a hash sign in the
database name is refused. Every refusal raises one fixed message that
holds no part of the URL, before any file is read and before a pool
exists. Twenty one cases pin this, five accepted and sixteen refused.
Five deliberate breaks each turned tests red: removing the scheme check,
the allowlist, the role check or the hash check, and raising without
suppressing the context. The first break of the scheme check did not
turn any test red, because the allowlist and the role check refused
every case in the file. A keyword string with listed keys only passed
without it. That case was added, and the break then failed it alone.
Each time the file was restored and its hash compared.

open_public_pool checks the URL and builds a pool that is not opened.
It does not read the password file, set the pool values or wait for the
first connection yet, and nothing calls it. Decisions 1 and 4 to 8 are
not finished.

## How to Verify

    pytest -q tests/architecture tests/presentation/public \
        tests/infrastructure/test_public_pool_url.py
