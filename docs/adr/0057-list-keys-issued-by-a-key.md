# ADR 0057: List the Keys a Key Has Issued

## Status

Accepted. Resolves the first Follow-up named in ADR 0056.

## Context

ADR 0056 let a key revoke keys it issued without needing
`keys:manage`, but gave no way to see what a key had issued in the
first place. The relationship was enforceable but not visible: an
operator or an owning key had no way to answer "what has this key
created" short of a direct database query.

## Decision

Add `GET /api-keys/{id}/issued`, returning every key whose
`issued_by` equals the id in the path, including revoked ones.

Authorization mirrors ADR 0056's revocation shape exactly, the same
two paths: a caller holding `keys:manage` may view any key's issued
list, or a caller may view its own list (`caller_id` equals the
requested id), with no scope required for that case at all. This
keeps the self-view right free, the same way owning a key already
grants control over what it created, viewing is a strictly smaller
right than revoking.

The response excludes `key_hash` (never exposed anywhere) and
`issued_by` (redundant, since every entry in a given response
shares the same issuer by construction). Revoked keys stay in the
list: an owner reviewing what it issued should see its complete
history, not only what remains active, the same reasoning
`list_active` elsewhere already treats as a separate, narrower
query from "everything that exists."

The repository gained `list_issued_by(issuer_id)`, implemented in
both Postgres and in-memory, backed by a new `idx_api_keys_issued_by`
index, the same reasoning `idx_api_keys_key_hash` already documents:
without it, this becomes a sequential scan as the table grows.

The service loads the requested issuer first, raising
`ApiKeyNotFoundError` if it does not exist, before authorizing, the
same not-found-before-authorization ordering `RevokeApiKeyService`
already uses, so a caller without rights over a given id learns
only whether that id exists, not what it issued.

## Consequences

- The result is capped at `MAX_ISSUED_KEYS_RETURNED` (100), the
  same pattern `ListJobsService` uses for its own cap, rather than
  paginated. A key that has issued more than 100 keys will see a
  truncated list, with no indication in the response that
  truncation occurred. Acceptable for now, since no key in this
  system currently issues anywhere near that many, but worth
  revisiting if that assumption changes.
- Revoked keys appearing in this list means the endpoint is not a
  simple mirror of what the caller could still act on, a human
  reading the response needs to check `revoked_at` on each entry,
  not assume every listed key is still live.

## Alternatives Considered

**Require `keys:manage` for any view, drop the self-view right.**
Rejected: this is a strictly weaker version of ADR 0056's own
reasoning. If ownership is enough to revoke a key, it is at least
enough to look at it.

**Exclude revoked keys from the list, matching `list_active`'s
behavior.** Rejected: this endpoint answers "what has this key
issued," a question about history, not "what is currently live,"
which `list_active` already answers for a different purpose.
Silently dropping revoked entries would make the list quietly
incomplete rather than clearly scoped.

## Follow-ups

- Pagination, if any key's issued list grows past the current cap
  in practice.
- Whether to indicate truncation explicitly in the response, if the
  cap is ever actually hit.
