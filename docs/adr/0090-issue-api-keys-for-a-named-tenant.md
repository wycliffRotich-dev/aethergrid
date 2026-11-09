# ADR 0090: Issue API Keys for a Named Tenant

## Status

Accepted. Written before any code. It became Accepted when
scripts/issue_api_key.py issues a key for a named tenant, creates the
tenant only when asked to, and prints its usage without a database. The
tests are written first and fail for the right reason, and one real run
against Postgres shows two keys in two tenants.

Related: ADR 0054, ADR 0055, ADR 0064, ADR 0075 and ADR 0082.

## Context

A key belongs to exactly one tenant (ADR 0064), and every read and write
the key makes is scoped to that tenant. The application can already issue
a key for any existing tenant. CreateApiKeyService takes either an issuer
or a tenant id, never both, and raises TenantNotFoundError when no tenant
has the id. TenantRepository can create a tenant, and saving the same
tenant twice is a no-op.

Nothing an operator can run reaches either. The script that issues keys
takes only a label and scopes, so every key it issues belongs to the
default tenant. Its own comment says so, "until this script takes a
--tenant option". No HTTP route creates a tenant. A deployment therefore
has one tenant unless someone writes to the database by hand, and the
isolation ADR 0064 defines cannot be shown on a deployed system.

The script also imports the application wiring at the top of the module.
That wiring builds the repositories on import and fails when
NEUROMESH_STORAGE_BACKEND is not set. As a result `--help` fails without
a backend, and two script test files could not be collected without one.

A tenant name is matched exactly, with case. Tenant.create trims
surrounding whitespace and gives every new tenant a fresh id, so calling
it twice with one name raises TenantAlreadyExistsError, because the name
is already held by a different id.

## Decision

1. `--tenant NAME` issues the key for the tenant with that name. The name
   is trimmed and matched exactly, with case. Without the option the key
   belongs to the default tenant, as it does today.
2. A tenant that does not exist is an error that names it. `--create-tenant`
   creates it first. `--create-tenant` without `--tenant` is a usage error.
3. A new application service, ResolveTenantService, returns the tenant
   with a given name. When none exists it creates one if
   create_if_missing is true, and raises TenantNotFoundError otherwise.
   The script calls the service and never a repository, and the service
   is reached through the dependencies module like the other services.
   Running the same command again returns the same tenant.
4. A line saying which tenant was used, and whether it was created, goes
   to standard error. Standard output is unchanged, because other tools
   read the key from it.
5. The script imports the application wiring inside main(), after the
   arguments are parsed. `--help`, parse_args and the test database guard
   work without a backend. The guard runs before any tenant is resolved
   or created, so a test database is refused before anything is written.
6. parse_args returns a frozen IssueArgs with the label, the scopes, the
   tenant name and the create flag. Tests that unpack the old pair change
   in the same commit as the code and are named in the Progress section.
7. No HTTP route creates, renames or deletes a tenant.

## Consequences

- An operator can give each team or customer its own tenant with one
  command per key, and the same command can be run again.
- A typo in a tenant name fails, and does not open a new boundary.
- Two keys in two tenants can be produced on any deployment, which makes
  tenant isolation checkable there.
- The two script test files can be collected without a backend.

## Not Claimed

- That two tenants are isolated from each other. ADR 0064 and ADR 0075
  decide that, and the tenant tests check it.
- That a tenant can be renamed or deleted. Neither is possible.
- That names which differ only in case are the same tenant. They are two
  tenants.
- That two operators creating one new name at the same moment both
  succeed. The second one fails with the repository's error and changes
  nothing.

## Alternatives Considered

- **Create the tenant whenever `--tenant` names an unknown one.**
  Rejected. A typo would open a new isolation boundary and issue a key
  into it without any error.
- **A separate script that creates tenants.** Rejected. Every use of the
  key script would need a second command before it, and a bootstrap line
  should be one command that is safe to run again.
- **An HTTP route that creates tenants.** Rejected here. It would add an
  authenticated surface and a new scope that widens reach, which needs its
  own ADR if it is ever wanted.
- **Call TenantRepository from the script.** Rejected. The script is the
  outermost layer, and the layer rules (ADR 0082) send it through a
  service.

## Follow-ups

- Use two keys in two tenants to check tenant isolation on a deployed
  system.

## How to Verify

```bash
env -u NEUROMESH_STORAGE_BACKEND python scripts/issue_api_key.py --help | head -n 1
```

It prints a line that starts with `usage:`. Before this change the same
command fails with a RuntimeError, because the backend is not set.

## Progress

2026-11-09. Written before any code. The script issues keys for the
default tenant only, and its usage cannot be printed without a backend.

2026-11-09. Accepted. `--tenant` and `--create-tenant` are in main
(#481), and the failure paths are pinned by tests (#482): a lost race
reaches the operator as an error with no key issued, and the test
database guard runs before a tenant is created. Each of the two new
tests failed against a deliberately broken script and passes against
the real one.

One real run on Postgres 16 (image
`postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`),
with the key script run from the host at a checkout of e3304e2, against
a database whose migrations 1 to 5 an earlier image had applied. The
database held one tenant, `default`, and one key, and no jobs. The
script then ran, in this order:

- `--tenant acme` for a tenant that did not exist exited 1 with
  `error: tenant 'acme' does not exist. Pass --create-tenant to create
  it.`, printed nothing on standard output, and left the tenant count
  at 1.
- `--tenant acme --create-tenant` and `--tenant globex --create-tenant`
  each printed `Created tenant` with the new id (acme
  8faecb20-c6ac-48ed-9fe5-43af72e0f698, globex
  a081e780-723a-4eb6-a599-3bee75a597c8) and issued one key.
- A join of api_keys to tenants showed three keys in three tenants:
  `local-dev` in default, `acme-runner` in acme and `globex-runner` in
  globex. The two new keys have only jobs:execute and no issuer.
- The same `--tenant acme --create-tenant` command run again printed
  `Using tenant` with the same id and left the tenant count at 3. It
  issued a fourth key, because every run issues a key.
- With NEUROMESH_STORAGE_BACKEND unset, the command under How to
  Verify printed a line starting with `usage:`.

The API checks below ran against an application image rebuilt from
the same checkout, whose migrate run applied nothing, so
schema_migrations still held five rows. Through the running API and
the real key lookup, not an overridden one, the acme key created a
job and read it back with a 200. The
globex key got a 404 for that job id and the identical status and
body for a random id, so a job in another tenant could not be told
apart from a missing one. The job row carries acme's tenant id.

Not claimed by this run: that two operators creating one new name at
the same moment fail cleanly on Postgres, since only the unique
constraint on tenants.name and the script's handling of
TenantAlreadyExistsError are shown, not the repository's translation
of one into the other. That response headers or timing do not
distinguish a foreign job from a missing one, since only the status
and body were compared. That tenant isolation holds beyond jobs,
which ADR 0064 and ADR 0075 and their tests decide.
