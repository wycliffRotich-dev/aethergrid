# ADR 0056: Allow a Key to Revoke Keys It Issued, Without keys:manage

## Status

Accepted

## Context

ADR 0055 closed the open path where any valid key could issue or
revoke any other key, by requiring the `keys:manage` scope on both
`POST /api-keys` and `POST /api-keys/{id}/revoke`. Its own
Follow-ups section named the next question directly: `keys:manage`
is a flat, all-or-nothing scope. A key holding it can revoke any
key in the system, owned or not, including one it has no
relationship to at all. A key that only ever needs to clean up
after its own integration, revoking sub-keys it issued itself, has
no narrower option than the same broad scope an operator uses to
administer the whole fleet.

`ApiKey` had no ownership field at the time ADR 0055 was written.
There was no way to grant a narrower capability, "manage what you
created," because the system had no record of what any key had
created.

## Decision

Add `issued_by: ApiKeyId | None` to `ApiKey`, set once at issuance
and never changed afterward. A key issued through `POST /api-keys`
records the authenticated caller as its issuer. A key issued
through `scripts/issue_api_key.py`, the bootstrap path that runs
with direct repository access and no authenticated caller, has
`issued_by = None`, the same as every key that existed before this
column did.

Revocation now succeeds through either of two independent paths:

1. The caller holds `keys:manage`. This remains the override from
   ADR 0055, working on any key regardless of ownership.
2. The caller is the key named in the target's `issued_by`. A key
   may revoke a key it issued, without needing `keys:manage` at
   all.

A key with `issued_by = None`, every legacy key and every bootstrap
key, has no owner, so only path 1 can ever reach it. This is
deliberate: there is no real issuer on record for those keys, and
fabricating one would misrepresent the audit trail rather than
improve it.

Issuance itself is unchanged by ownership: creating a new key still
requires `keys:manage` outright, with no ownership exception,
since issuance has no existing target to hold an ownership
relationship to.

## Consequences

- **The authorization decision for revocation moved from the route
  to the service, the one deliberate departure from this
  codebase's standing convention that the gate lives at the
  route** (see ADR 0054's own Consequences, and the comment in
  `jobs.py`: *"CreateJobService itself is policy-free, so any
  future route that accepts a command must call
  authorize_job_creation"*). Deciding whether a caller may revoke a
  specific key requires that key's `issued_by`, a fact that does
  not exist until the target is loaded from storage, and no route
  in this codebase currently has its own repository access; every
  route depends only on a service. Rather than give the route a
  new, unprecedented kind of dependency just to peek at the target
  before calling the service that will load it again anyway, the
  check was moved into `RevokeApiKeyService`, immediately after it
  loads the target and before any mutation. The decision itself
  remains a pure domain function, `authorize_key_revocation`, with
  no I/O and no framework types; what moved is only which layer
  calls it. Issuance's authorization check stays at the route,
  unchanged, since it has no target to load.
- Not-found is still checked before authorization, the same
  ordering as before this ADR: a caller without any rights over a
  given key id still learns whether that id exists (404) versus
  exists but is denied (403). Key ids are UUIDs returned only to
  callers who already hold API access, not guessable secrets, so
  this is a minor information distinction, not a credential leak,
  but it is named here rather than left for a reviewer to notice
  unexplained.
- Every pre-existing key, and every key issued by the bootstrap
  script, has `issued_by = None` and so can only be revoked by a
  `keys:manage` caller, exactly the ADR 0055 behavior, unchanged
  for those keys.
- A key holding `keys:manage` can still issue a key with any scope,
  including `keys:manage` itself. Ownership does not constrain
  issuance, only revocation.

## Alternatives Considered

**Give the route its own repository access to load the target
before calling the service.** Rejected: no route in this codebase
currently depends on a bare repository, only on services. Adding
one, solely so a route could make a read it would otherwise
duplicate inside the service a moment later, is a larger and more
novel departure from this codebase's layering than moving one
scope decision into the one service that already loads the data it
needs.

**Treat `keys:manage` as the only path, drop ownership entirely.**
This is the ADR 0055 status quo. Rejected because it was already
named as insufficient in ADR 0055's own Follow-ups: a key that
issues sub-keys for its own purpose has no way to manage its own
sub-keys without also being trusted over every other key in the
system.

**Backfill an owner for keys that predate this column**, so no key
is left with `issued_by = None`. Rejected: there is no real record
of who issued any pre-existing key under the single-tier or
`keys:manage`-only models. Inventing an owner would misrepresent
the audit trail for a story a reviewer might actually rely on,
rather than honestly recording that the information was never
captured.

## Follow-ups

- `issued_by` is a single flat link, not a chain. If key A issues
  key B, and key B issues key C, A has no standing relationship to
  C. Whether a transitive "issued by an ancestor" rule is ever
  needed is open, and deliberately not addressed here.
- There is currently no way to see which keys a given key has
  issued, short of a direct query. A `GET /api-keys/{id}/issued`
  listing endpoint, or including issued keys in some existing
  response, would make the ownership relationship this ADR
  introduces actually visible to an operator rather than only
  enforceable.
