# ADR 0055: Scope API Key Issuance and Revocation

## Status

Accepted

## Context

ADR 0054 scoped `Job.command` behind `jobs:execute`, closing the
path where any valid key could make a worker run an arbitrary
command. While writing that ADR, a second gap was noticed and
recorded as a follow-up rather than fixed immediately: `POST
/api-keys` and `POST /api-keys/{id}/revoke` had no scope check at
all. Any valid key, including one freshly issued with zero scopes,
could mint a new key with any scope available at issuance time, or
revoke any other key in the system.

`ApiKey` has no ownership field. There is no `issued_by` or
`owner_id`, so there was never a notion of "a key can manage keys
it issued" to violate. Every key stood in the same flat trust
relationship to every other key. A key meant only to submit jobs
could revoke the key an operator uses to manage the cluster, or
issue itself a sibling key, with nothing in the system to stop it.

This is a distinct trust boundary from command execution. A key
that can run arbitrary commands on a worker is dangerous in one
direction. A key that can mint or kill any other key is dangerous
in a different, more structural way: it can escalate its own
reach or cut off everyone else's, regardless of what scopes it
personally holds.

## Decision

Require the `keys:manage` scope to call `POST /api-keys` or `POST
/api-keys/{id}/revoke`. A key without it gets a 403 naming the
missing scope, the same shape `jobs:execute` already uses.

Unlike `jobs:execute`, there is no unscoped path left standing.
`jobs:execute` only gates setting a command, a key without it can
still create resource-only jobs. Key management has no equivalent
lesser capability to fall back to: issuing and revoking are the
entire surface of that router, so the gate covers all of it.

`keys:manage` is granted the same way `jobs:execute` is: only by
`scripts/issue_api_key.py`, run locally with direct repository
access, never through the API. The script required no changes,
since its `--scope` flag already validates against the shared
`KNOWN_SCOPES` registry rather than a hardcoded list.

The check lives in a new pure function, `authorize_key_management`,
parallel to `authorize_job_creation`: no I/O, no framework types,
just a scope check that raises `ScopeDeniedError` on failure. Both
route handlers call it before doing anything else, so a denial
never reaches the service layer or the repository.

## Consequences

- Every key issued before this change has no scopes, per ADR 0054,
  so every existing key loses the ability to manage other keys.
  Whoever operates this deployment needs at least one key reissued
  with `keys:manage` to keep provisioning or revoking credentials.
- A key with `keys:manage` can still issue a new key with any
  scope, including `keys:manage` itself, or revoke any key in the
  system, including the one currently authenticating the request
  that revokes it. There is still no ownership model. A key that
  holds `keys:manage` is fully trusted over all keys, not just
  ones it issued. That is a deliberate simplification, not an
  oversight: introducing ownership means a new persisted field, a
  migration, and a decision about what existing keys should be
  treated as owning, which is a larger change than closing the
  open gate this ADR addresses.
- `CreateApiKeyRequest` still has no `scopes` field, confirmed by
  an existing test. A caller with `keys:manage` can issue new keys
  over HTTP, but still cannot grant them any scope that way. Scopes
  of any kind remain issuable only through the script.

## Alternatives Considered

**Add ownership instead of a flat scope.** A rule like "a key can
only revoke a key it issued" is a more precise fix, and the ADR
0054 follow-up language gestured at it. Rejected for now because
it requires a schema change and a migration decision for keys that
predate ownership tracking, and because a flat `keys:manage` gate
already closes the actual reported gap, any key managing any key
with no check at all. Ownership is a refinement on top of a scope
that already exists, not a replacement for it, and can be added
later without reversing this decision.

**Leave the gap documented but open**, as ADR 0054 did. Rejected
because a known, unscoped privilege escalation path sitting in a
public repository is a standing risk with no offsetting benefit to
leaving it open. Nothing about the fix was blocked on a larger
design decision once ownership was taken off the table for this
pass.

## Follow-ups

- Add ownership to `ApiKey` so a key can only revoke a key it
  issued, with `keys:manage` acting as an override rather than the
  only gate. Deserves its own ADR once a migration plan exists for
  keys issued before ownership was tracked.
- Decide whether `CreateApiKeyRequest` should ever accept a
  `scopes` field for a caller holding `keys:manage`, or whether
  scope grants should remain script-only indefinitely.
