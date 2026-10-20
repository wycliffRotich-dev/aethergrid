# ADR 0076: Run the README Setup Blocks in CI

## Status

Accepted. A workflow executes the README's setup blocks on a clean
runner. It has passed on a pull request and on `main`, and it has been
shown to fail on two deliberate breaks.

Related: ADR 0058, ADR 0060, ADR 0061 and ADR 0063.

## Context

ADR 0063 records a clean clone test that found a real fault, a
restrictive umask that made `schema.sql` unreadable to the container.
That test was manual, so nothing repeated it.

A second clean clone test, run on a fresh clone of `main`, found two
more faults on the documented path. `python -m venv` fails on a stock
Ubuntu machine, where only `python3` exists until a venv is active. And
`scripts/issue_api_key.py` raises a `RuntimeError` when
`NEUROMESH_STORAGE_BACKEND` is unset, because the key block never
exported it. The test block had the same gap, and `pytest` stopped at
conftest import for the same reason.

All three faults share one cause. The author's shell already held the
right environment, so the README was never run against a clean one. The
container hardening workflow starts the compose stack on a clean runner,
but it never creates a venv, issues a key or runs `pytest`, which is
where the faults were.

## Decision

1. CI executes the README's setup blocks. They are read from
   `README.md` by `scripts/readme_blocks.py`, not copied into the
   workflow, because a second copy would drift from the first.
2. Every `bash` fence in the README carries a comment directly above it.
   `<!-- ci:readme step=N name=NAME -->` means CI runs it.
   `<!-- ci:readme skip name=NAME reason=REASON -->` records why it does
   not. The comments render as nothing.
3. The extractor fails on an unmarked `bash` fence, on steps that are
   not exactly 1 to N, on a repeated name, on a marker not directly above
   a fence, and on fewer than three run blocks. The last rule means
   deleting markers cannot make the job pass by running nothing. The
   rule that every block is classified follows the route classification
   test of ADR 0064.
4. Blocks run in step order, not file order, because the tests block
   assumes the setup is already done. Each step runs in its own `bash`
   process, as a reader's terminal would. This also keeps the test
   block's `NEUROMESH_DATABASE_URL` from reaching the key script, whose
   guard refuses any database name containing `test`.
5. The extractor prints block bodies verbatim. Adapting them to an
   existing checkout is the workflow's job. Step 1 drops the `git clone`
   and `cd aethergrid` lines and fails unless it drops exactly two.
   Step 3 runs with `.venv` active, as the README prose assumes.
6. Step 2 captures the key from the line after the `Issued API key`
   header, requires 43 characters, masks it, and requires an
   authenticated `GET /nodes` to return 200. Failure output hides the
   key line.
7. The workflow runs on pull requests and pushes to `main` that touch
   the files the README depends on, and on manual dispatch.

## Evidence

- The job passed on the pull request that added it and on `main`. The
  `main` run reported 927 passed in 75.73 seconds. The 24 tests more than
  a local run of the same commit before the extractor are the extractor's
  own.
- Proof 1 (pull request 390, closed unmerged): removing the backend
  export from the key block turned the job red at step 2 with
  `RuntimeError: NEUROMESH_STORAGE_BACKEND is not set`.
- Proof 2 (pull request 391, closed unmerged): removing it from the tests
  block left step 2 green and turned step 3 red with the same error.

Both proofs follow the method of ADR 0061: a check that has only passed
has not been shown to catch anything.

## Consequences

- Step 3 repeats the full suite, which the `test` job already runs. It
  is kept verbatim because the point is to run the README as written. The
  path filter limits how often it is paid.
- If a required status check is configured for this workflow, the path
  filter leaves it pending on pull requests that touch none of the listed
  files.
- Adding a `bash` fence to the README now requires a marker, so a new
  block cannot escape the check.
- The marker format is a contract. Renaming a block or changing a step
  number is a change to the workflow's behaviour.

## Not Claimed

- CI proves the commands run on an Ubuntu 24.04 runner with Docker. It
  does not prove the prose is clear, and it says nothing about macOS,
  Windows, ARM or other shells.
- The runner's `python3` is 3.12. The README path is not run on 3.11.
- The frontend block is skipped on purpose, because it starts a dev
  server that never exits.

## Alternatives Considered

- **Copy the commands into the workflow.** Rejected. The copy drifts
  from the README, which is the failure being fixed, one level up.
- **Extract blocks by line number.** Rejected. Any edit above a block
  silently breaks the job.
- **A manual checklist before releases.** Rejected. ADR 0063's manual
  test found a fault and nothing repeated it.
- **Extend the container hardening workflow.** Rejected. That workflow
  asserts container properties. Mixing a venv, a key and a test run into
  it would blur what each failure means.
