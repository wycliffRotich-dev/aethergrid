# ADR 0101: Give Every Workflow Job a Timeout and Test the Rule

## Status

Accepted.

Related: ADR 0060 and ADR 0100.

## Context

A job with no timeout-minutes runs for up to six hours before GitHub
stops it. ci.yml set none on its four jobs and deploy-site.yml none on
its one. The other three workflows already did.

On 2026-11-15 the test job on Python 3.11 ran 23 minutes 36 seconds.
The same job on Python 3.12 took 2 minutes 23 seconds. Eight tests in
tests/infrastructure/test_public_app_role_script.py each waited between
101 and 218 seconds. Nothing stopped the run, and it passed. A rerun of
that job on the same commit took 2 minutes 23 seconds with no such wait.

## Decision

1. Every job in every workflow sets timeout-minutes at the job level.
2. The values come from observed run times: test 15, frontend 10,
   changes 5, e2e 20 and deploy 10.
3. tests/supply_chain/test_job_timeouts.py fails any job that lacks one.
   A timeout on a step does not count for its job. The test has cases
   that feed it a bad input and expect it to be flagged.

## Consequences

- A stalled job is cancelled and fails the run, so the stall is seen and
  the runner is freed.
- A healthy run that needs longer than its limit is cancelled too. The
  limits are about six to seven times the normal time for test and e2e
  and about ten times for frontend. The changes job takes seconds, and
  the normal time of the deploy job was not observed. The first healthy
  run that hits a limit should raise it.
- A new job in any workflow must choose a limit in the same change.
- The test reads job layout with a pattern. It assumes jobs indented two
  spaces and their keys four. A workflow laid out differently would pass
  without being checked.

## Not Claimed

- That the cause of the 23 minute run is known. The rerun was fast,
  which points at the runner and no further.
- That every healthy run fits its limit. Few runs were observed.

## Alternatives Considered

- **No limits, relying on the six hour default.** Rejected. A stalled job
  holds a runner for hours, and the run shows as pending, not failed.
- **Set limits without a test.** Rejected. The next job added to any
  workflow would have none, and ADR 0100 chose to test its rules.
- **A timeout on the pytest step only.** Rejected. A stall in setup or
  in a service container start would not be covered.
- **Find the cause of the slow run first.** Deferred. It did not recur,
  and a limit helps whatever the cause. A report of the slowest tests in
  the pytest output would show it next time, and is a separate change.

## Progress

2026-11-15. The test failed on ci.yml and deploy-site.yml and passed on
the other three. The passes were checked by counting the jobs and the
timeouts in each file, and the counts matched.

2026-11-15. Removing the timeout from deploy-site.yml failed the test
for that file and no other. The file was restored and its hash compared.

2026-11-15. The rule and its test were merged in PR 516 before this
ADR was committed. This record was added afterwards.

## How to Verify

    pytest -q tests/supply_chain/test_job_timeouts.py
