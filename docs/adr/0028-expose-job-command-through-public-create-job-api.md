# ADR 0028: Expose Job.command Through the Public CreateJobRequest API

## Status

Proposed

## Context

ADR 0012 built real subprocess execution with enforced timeouts,
`Job.command` and `Job.exit_code`, fully tested at the service
layer, but deliberately did not expose `Job.command` through the
public `CreateJobRequest` API. It named the open question
directly: whether an authenticated caller should be trusted with
arbitrary command execution is a separate decision about scope
and blast radius, and it hadn't been made yet, because at that
point authentication itself didn't exist.

ADR 0015 has since shipped API key authentication for every
route. ADR 0020 partially closed the gap ADR 0012 left open, by
letting an assigned worker *read* the command of the job it was
already given, scoped narrowly to `GET /workers/{worker_id}`.
That ADR was explicit that it did not touch `CreateJobRequest`:
"`CreateJobRequest` remains exactly as ADR 0012 left it. A caller
creating a job still cannot set an arbitrary command through the
public surface."

That gap is still open today. `Job.command`'s own docstring
still describes the blocker as an "unauthenticated HTTP
endpoint," which is now stale: authentication exists (ADR 0015).
The real remaining question isn't whether a caller is
authenticated, it's what any given authenticated caller should be
trusted to do, since ADR 0015 defined a single key tier for the
whole system, with no distinction between roles.

Two separate deployments hold different risk here:

- **Local development**: issuing a key requires direct database
  access (`NEUROMESH_DATABASE_URL`, `scripts/issue_api_key.py`).
  Anyone able to abuse a locally-issued key to run arbitrary
  commands already had direct DB write access, a strictly larger
  blast radius than remote command execution grants them.
- **Production (Render)**: ADR 0025 documents issuing keys via
  Render Shell specifically because that's the only place
  production keys get minted. Today, the repo owner is the only
  person who has done this. The moment `Job.command` becomes
  publicly settable, whoever holds a Render-issued key gains the
  ability to execute arbitrary commands on whatever machine runs
  a worker agent in production.

## Decision

`command` becomes an optional field on `CreateJobRequest`,
accepted as a list of strings (`list[str] | None`), matching the
existing shape of `Job.command`. It is threaded through
`CreateJobService.execute()` into `Job(...)` at creation time,
gated by the same single API key requirement every other route
already uses (ADR 0015). No new key tier is introduced.

This mirrors the reasoning ADR 0020 already used to reject a
second key tier when it unblocked ADR 0019: introducing tiered
credentials before a real, measured multi-holder risk exists
would be exactly the premature complexity ADR 0018 argues
against. The risk today is theoretical in production (one person
holds a key) and non-escalating locally (a key holder already has
DB access). Building a permission system for a threat actor that
doesn't exist yet is not this project's pattern.

This decision is explicitly scoped and time-bound, not a
permanent judgment that a single tier is always sufficient:

- Command-execution capability in production is scoped in
  practice to whoever holds a Render Shell-issued key. Today that
  is the repo owner alone.
- **This must be revisited before that stops being true.**
  Specifically: before any key is issued via Render Shell to
  anyone other than the repo owner, e.g., a contributor, a demo
  user, a teammate, this decision needs to be reopened, and a
  tiered credential model (deferred by ADR 0020, still deferred
  here) needs to actually be built first.

`Job.command`'s docstring is updated to drop the stale
"unauthenticated" framing and instead point at this ADR.

## Consequences

### Positive

- Closes the loop ADR 0012 opened and ADR 0020 partially
  addressed. Real subprocess execution, already fully built and
  tested at the service layer, becomes reachable end to end: a
  caller can set a command, a worker agent can read it (ADR
  0020), and it actually runs (ADR 0012).
- No new complexity introduced. One key tier, one auth check,
  consistent with every other route.
- The revisit condition is concrete and checkable ("has a
  non-owner key been issued in production") rather than a vague
  "reassess later."

### Negative

- Any valid API key can now trigger arbitrary command execution
  on a worker machine. This is a real, not hypothetical, widening
  of what a compromised or leaked key can do, even though today's
  actual population of key holders is one person.
- The single-tier model means this can't be selectively granted.
  The day a second key holder exists in production, this decision
  is under-scoped and must be revisited, not optional cleanup.

## Alternatives Considered

### Restrict command to an allowlist of permitted binaries/commands

Rejected for now.

Would meaningfully shrink the blast radius, but adds real
complexity (maintaining the list, deciding what's on it, handling
legitimate use cases that need arbitrary scripts) for a risk that
is currently theoretical. Worth revisiting if the threat model
changes, e.g., third-party job submission becomes a real use case.

### Introduce a separate "agent" or "admin" API key tier before exposing this

Deferred, same as ADR 0020.

The correct long-term answer once multiple people hold production
keys. Premature today: it would add a real change to the
authentication model (ADR 0015) to guard against a risk that, as
of this ADR, has exactly one possible actor.
