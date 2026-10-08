# ADR 0065: Scope the API Key Repository by Tenant

## Status

Accepted. This ADR records how ADR 0064, points 4 and 5, were applied
to API keys. ADR 0064 stays Proposed until its enforcement test
merges, and nothing here changes that.

## Context

The first tenancy change (#318) gave every `ApiKey` a required
`tenant_id` and added the column and its constraints. The key routes
still looked keys up across tenants, so a caller in one tenant could
revoke or list a key in another. This change scopes those lookups.
ADR 0064 sets the rule but leaves several cases open: how
authentication finds a tenant, what a save of an existing id means,
and what happens to a method with no tenant to pass.

## Decision

1. **The credential lookup is named, not exempted.** Authentication
   learns the tenant from the key, so its lookup cannot take one. It
   is renamed `get_by_hash_across_tenants`, and only authentication
   calls it. The rule test has no exception for it.

2. **A save is scoped by the tenant its entity carries.** The tenant
   travels inside the `ApiKey` and cannot change. In Postgres the
   upsert updates only when the stored row has the same tenant. If it
   does not, no row is affected and the repository raises
   `ApiKeyTenantConflictError`. The in-memory repository raises it in
   the same case. Key ids are generated, so reaching this means a bug
   in the caller, and it is reported instead of ignored.

3. **`list_active` is removed.** It had no caller outside tests.
   Keeping it as `list_active_across_tenants` would leave a fleet-wide
   read on the contract with no system actor behind it, which is what
   the suffix is meant to rule out.

4. **The tenant filter runs before the scope decision.** Revoke and
   list-issued look the key up with the caller's tenant first. A key in
   another tenant raises the same not-found as a missing id, so a
   caller without rights never receives a 403 for a key that exists.

5. **The rule is checked by parameter types.** A test reads the
   abstract methods of each scoped repository. A method passes if it
   takes a `TenantId`, takes an entity that carries a tenant, or is
   named `_across_tenants`. A method named `_across_tenants` that takes
   a `TenantId` fails, because the name would be wrong. Two small
   repositories built to break each rule keep the check itself honest.
   A repository joins the test in the same change that scopes it.

6. **"Nothing was saved" is checked with a test repository.** A
   `RecordingApiKeyRepository` in `tests/support` records saves. The
   production repositories gain no method for tests.

## What the review of the first change found

- The Postgres upsert in #318 matched on id only. Saving a key object
  whose id was held by another tenant would have overwritten that
  row's `revoked_at`, `last_used_at` and `scopes`. No route could
  reach it, but the contract allowed it. It is fixed here, and the
  contract test fails when the guard is removed.
- The in-memory `save` replaced a stored key by id with no tenant
  check. A new contract test found it. It is fixed here.
- The first version of the guard ignored a cross-tenant save without
  an error. That hides the bug it guards against, so it now raises.

## Consequences

- A foreign key and a missing key give the same response on every key
  route, whether or not the caller holds `keys:manage`.
- Both backends pass one shared contract for these rules, and the
  Postgres guard and the in-memory lookup filter were each removed by
  hand to confirm that the tests fail without them.
- Only `ApiKeyRepository` is under the rule test. Jobs, nodes,
  workers, leases and events are not scoped yet, and no document may
  describe the system as multi-tenant until ADR 0064 is Accepted.
- A save that conflicts on tenant now raises. A caller that expected
  it to be ignored would see an error, and none exists in the code.

## Alternatives Considered

**Exempt the credential lookup inside the test.** Rejected. A list of
method names kept in the test is a silent exception. A name that
says what the method does needs none.

**Ignore a cross-tenant save.** Rejected. It matches how ordinary
saves behave, but it fails quietly on a security write.

**Keep `list_active` under a new name.** Rejected, see point 3.

**Add recording to the in-memory repository.** Rejected. Test-only
behaviour does not belong on a production class.

## Follow-ups

- Add each repository to the rule test as it is scoped.
- Scope the remaining resources, ADR 0064 points 2 and 5 to 8.
- Add a `--tenant` option to the bootstrap script, which still places
  keys in the default tenant.
