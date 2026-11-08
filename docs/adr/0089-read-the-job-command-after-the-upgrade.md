# ADR 0089: Read the Job Command After the Upgrade

## Status

Proposed. Written before any code. It becomes Accepted when the
rehearsal reads the seeded job's command back from the new API, the
tests were written first and failed for the right reason, and one real
run from v0.6.0 has shown whether the worker still holds the job when
the command is read (decision 4).

Related: ADR 0020, ADR 0028, ADR 0054, ADR 0088.

## Context

ADR 0088 lists one follow-up: read the job's command through the worker
route, which is the only read that returns it (ADR 0020). GET /jobs/{id}
and the job list leave the command out by design.

The seeded job has no command. JOB_PAYLOAD says so, and
test_the_job_has_no_command pins it. A migration that dropped, emptied
or reshaped the stored command would therefore pass the rehearsal today.

Setting a command needs the `jobs:execute` scope (ADR 0054). The key the
rehearsal uses is issued inside the old release's own service by
ISSUE_KEY_SNIPPET, with no scopes, and
test_the_snippet_issues_a_default_tenant_key_without_scopes pins that.
The service of v0.6.0 takes the same `scopes` argument as main, so the
old release can issue a scoped key itself.

GET /workers/{id} returns the command as `running_job.command`, and
`running_job` is present only while the worker holds a job. The seeded
worker is managed by an agent, so nothing runs the command, but the
scheduler assigns the job and takes the lease. ADR 0088 decision 6
records that the new API may reclaim a lease that nothing renewed.

## Decision

1. The rehearsal key is issued with the `jobs:execute` scope, inside the
   old release's service, so a key from before the upgrade is still the
   key that is read with. The scope is written in the snippet as the
   string "jobs:execute" and not imported, because the snippet runs in
   the old release and must not depend on a module that release may not
   have. A test pins that the string equals JOBS_EXECUTE on main, so the
   two cannot drift apart.
2. The seeded job gets a fixed command, held in one constant in the
   script. Nothing runs it, because an agent manages the worker and no
   agent is started. A test pins that the payload stays valid for
   CreateJobRequest.
3. After the three reads of ADR 0088, the rehearsal checks that
   `running_job.command` in the worker body equals the seeded command.
   A difference ends the run, and the message names the route and says
   the command differs. The command is never printed, because a command
   may hold data.
4. The check requires `running_job` to be present. If a real run shows
   that the new API reclaims the lease before the read, that is recorded
   in this ADR and the decision is revisited. The check is not weakened
   to pass.
5. The two tests that pin the old seed, test_the_job_has_no_command and
   test_the_snippet_issues_a_default_tenant_key_without_scopes, change
   in the same commit as the code that makes them false. They are
   replaced by tests of the new behavior and are not deleted.

## Consequences

- A migration that loses or alters a stored command fails the rehearsal.
- The rehearsal key now carries a scope that widens what it may do. It
  is issued in a throwaway environment and torn down with it.
- The seed holds a command, so ADR 0088's statement that the job has no
  command no longer describes the seed. Its record stays as written.

## Not Claimed

- That the command runs, or that any agent can execute it.
- That any command other than the seeded one survives.
- That the lease survives startup. Decision 4 leaves that to a real run.
- That the check works from an old release other than v0.6.0.

## Alternatives Considered

- **Read the command from the database.** Rejected. It would not show
  what the API serves, and the worker route decodes the stored value.
- **Read it through GET /jobs/{id}.** Rejected. That route leaves the
  command out by design (ADR 0020).
- **Issue the scoped key on the new release.** Rejected for the reason
  in ADR 0088: it would not show that a key from before the upgrade
  still works.
- **Import the scope name into the snippet.** Rejected for decision 1.

## Follow-ups

None yet.

## How to Verify

```bash
grep -c "running_job" scripts/upgrade_rehearsal.py
```

It prints a number above 0 once the rehearsal reads the command.

## Progress

2026-11-08. Written before any code. read_back checks the status and
the id of three rows, and the seeded job has no command.
