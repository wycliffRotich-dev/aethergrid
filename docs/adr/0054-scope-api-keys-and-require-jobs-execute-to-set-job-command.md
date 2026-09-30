# ADR 0054: Scope API Keys, and Require jobs:execute to Set Job.command

## Status

Accepted

Follows up ADR 0028. ADR 0028 is left unchanged as the
historical record of what was known and decided at the time;
this ADR is the follow-up that ADR 0028 itself called for.

## Context

ADR 0028 exposed `Job.command` through `CreateJobRequest`, gated
by the single API key tier from ADR 0015. It accepted that only
because exactly one person held a key, and it named its own
revisit condition: before any key is issued to anyone other than
the repo owner, a tiered credential model must be built first.

That condition has been met. The project is under external
review, where reviewers clone the repository and mint their own
keys, and an in-house deployment implies more than one key
holder. ADR 0045 also makes one key per fleet agent the intended
pattern, so a real deployment holds many keys, not one.

Under the single tier, every valid key can set an arbitrary
argv-style command, and a worker agent executes it as a real
subprocess (ADR 0012). A leaked or over-shared key is therefore
remote code execution on worker machines. There was no way to
let a key submit ordinary jobs without also letting it run
arbitrary commands.

ADR 0020 and ADR 0028 both deferred a tiered model as premature.
This ADR builds the smallest change that closes the named gap
and nothing more.

## Decision

`ApiKey` gains `scopes: frozenset[str]`, empty by default, and
`has_scope()`. A set rather than a boolean, so a second scope
later needs no schema change.

The scope vocabulary is closed and lives in one place,
`app/domain/value_objects/api_key_scope.py`. It holds one scope,
`jobs:execute`. `ApiKey.issue()` rejects anything outside it,
including a bare string, so a typo such as `job:execute` raises
at issuance instead of silently granting nothing. Loading a
stored key is not validated, so a scope that later leaves the
vocabulary is inert rather than a lockout.

`jobs:execute` is required when, and only when,
`CreateJobRequest.command` is not `None`. The test is `is None`,
not truthiness, so an empty command list still counts as setting
a command. The request schema already rejects an empty list with
a 422, so over HTTP that edge is unreachable, but the rule stays
correct if that validator ever changes. A key without the scope
can still create resource-only jobs exactly as before.

The rule is a pure domain policy, `authorize_job_creation(scopes,
command)` in `app/domain/services/job_authorization.py`, raising
`ScopeDeniedError`. It is called from the one route that accepts
a command, `POST /jobs`, which maps the error to 403 with a
detail naming the missing scope and logs every denial with the
key id, the scope and the route. It is not a route-level
dependency layered like `require_rate_limit`, because whether
the scope is needed depends on the request body, and a per-route
dependency cannot express "only when command is set" without
parsing the body itself.

`CreateApiKeyService` accepts scopes and defaults to none.
`scripts/issue_api_key.py` gains a repeatable `--scope` flag,
restricted to the known vocabulary and defaulting to none.

Scopes can be granted only by that script, with direct
repository access. `POST /api-keys` cannot grant them:
`CreateApiKeyRequest` has no scopes field, a test pins that, and
the service it calls issues keys with no scopes. Otherwise any
valid key could mint itself a `jobs:execute` key and the scope
would protect nothing.

Worker agents need no scope. They read the command of their
assigned job through `GET /workers/{worker_id}` (ADR 0020) and
never create jobs.

### Audit of paths that can set Job.command

| Path | Can it set a command? | Result |
| --- | --- | --- |
| `POST /jobs` | Yes, the only one | Gated by `jobs:execute` |
| `POST /jobs/{job_id}/retry` | No. `Job.retry()` resets node, timestamps, exit code and cancellation, never `command` | Safe |
| `POST /jobs/{job_id}/cancel` | No request body | Safe |
| `POST /api-keys` | Cannot grant scopes, so cannot mint a key that may set a command | Safe |
| Worker and node routes | No request schema carries `command`; workers only read it | Safe |
| Repository row-to-entity reads | Rebuild stored jobs, accept no caller input | Safe |
| Indirect mutation | No `.command =`, `dataclasses.replace` or `setattr` in `app/` | Safe |

`CreateJobService` is constructed only by `get_create_job_service`
and used only by `POST /jobs`.

### Migration

`schema.sql` adds `api_keys.scopes TEXT[] NOT NULL DEFAULT '{}'`
with an idempotent `ADD COLUMN IF NOT EXISTS`, so it is safe to
apply to fresh and existing databases. Every key issued before
this change therefore has no scopes, including the owner's. A key
that could execute commands under the old single-tier model does
not keep that power silently.

Re-granting is explicit: issue a new key with
`python scripts/issue_api_key.py <label> --scope jobs:execute`,
move whatever used the old key to it, then revoke the old key.
This rotates the secret. No separate grant script is built;
reissuing matches this codebase's preference for explicit over
implicit, and a grant script can be added later if rotation
proves painful.

`PostgresApiKeyRepository` reads scopes tolerantly, so a
database that has not yet received the column reads as no scopes
and cannot break authentication.

## Consequences

### Positive

- Discharges the revisit condition ADR 0028 set for itself.
  Command execution is a capability granted per key at issuance,
  not something every key inherits.
- Fails closed for the new capability. A key with no scopes
  cannot set a command, and a mistyped scope is rejected instead
  of ignored.
- The migration forces a conscious re-grant for every
  pre-existing key instead of grandfathering broad power.
- Each rule was verified by mutation, not only by passing tests:
  removing the check, switching to a truthiness gate, dropping
  scopes in the service, dropping scopes in the Postgres `save()`,
  and skipping validation in `issue()` each fail exactly the tests
  written to catch them.

### Negative

- Authority remains ambient for everything else. An empty scope
  set means everything that is not explicitly gated, a deny-list
  model. A future route gated behind a new scope is open to
  existing keys until that scope exists, and gating an already
  open route later is a breaking change.
- Re-granting rotates the secret. The dashboard's Submit Job form
  sends `command` through `POST /jobs`, so a key issued before
  this change gets a 403 when it submits a command, until it is
  replaced with a key carrying `jobs:execute`. The same applies
  to any automation that creates jobs with a command. The
  dashboard's API client reports only the status code, not
  the server's message, so the form does not say which scope
  is missing.
- The scope is coarse. A key holding `jobs:execute` can run any
  command. This ADR controls who may submit commands, not what
  they may do. It is not a sandbox.
- The gate lives at the route. `CreateJobService` itself is
  policy-free, so any future route that accepts a command must
  call `authorize_job_creation`.
- Any valid key can still issue and revoke other keys, including
  revoking the owner's. That does not escalate command execution
  but it is a trust gap, recorded below as a follow-up.

## Alternatives Considered

### Allowlist model with a wildcard scope for legacy keys

Rejected for now. A complete allowlist is more explicit, but it
requires every route to declare its scope and migrates every
existing key to a wildcard, a much larger change than the one
gap this ADR targets.

### Keep existing keys able to execute commands

Rejected. It preserves the exact silent retention of power this
ADR exists to remove.

### A boolean `can_execute` flag

Rejected. It cannot grow into a second capability without
another migration.

### A route-level `require_scope` dependency

Rejected, as described under Decision: the requirement depends
on the request body.

### Restrict commands to an allowlist of binaries

Still deferred, as in ADR 0028. It would shrink the blast radius
of a `jobs:execute` key and is worth revisiting if third-party
job submission becomes a real use case.

### Named agent and admin key tiers

Rejected in favor of scopes. Named roles bundle capabilities
together, and only one capability needs separating today.

## Follow-ups

- Issuing and revoking keys is open to any valid key. A scope for
  key management, and a rule that one key cannot revoke another
  without it, deserves its own ADR.
- If rotation on re-grant proves painful, add a script that grants
  a scope to an existing key.
- Show the server's error message for a 403 in the dashboard
  API client, so a missing scope is visible to the person who
  hit it.
