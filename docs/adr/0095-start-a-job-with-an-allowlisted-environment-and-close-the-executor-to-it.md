# ADR 0095: Start a Job with an Allowlisted Environment and Close the Executor to It

## Status

Accepted.

Related: ADR 0028, ADR 0054, ADR 0058, ADR 0080 and ADR 0094.

## Context

A job's command is a real subprocess (ADR 0028). The supervisor started it
with Popen and no env argument, so the command received the whole
environment of the process that ran it, credentials included.

Removing variables from what the command receives is not enough on its own,
because the command is a child of that process and runs as the same user.
The container hardening of ADR 0058 does not close this by itself. It limits
what a command does to the host.

## Decision

1. The supervisor builds the command's environment from an allowlist:
   HOME, LANG, LC_ALL, PATH, TMPDIR and TZ. Everything else stays behind,
   including a secret that nobody thought to name.
2. NEUROMESH_JOB_ENV_PASSTHROUGH holds a comma separated list of further
   names that the operator chose to pass to every job. A name that is not
   set is skipped, and the setting itself is not passed.
3. The supervisor keeps its own environment, because it needs the
   interpreter settings of its owner. Only the command's environment is
   built.
4. app/application/process_hardening.py closes a process to its children.
   The supervisor, the agent (scripts/run_agent.py) and the API (the
   lifespan) each call it first, because Linux resets the setting when a
   process starts another program.
5. A kernel that refuses the call stops the process. A process that cannot
   close itself must not run jobs.
6. The module uses the standard library only, because the supervisor starts
   once for every job. A test enforces it.

## Consequences

- A job that relied on an inherited variable, such as a proxy setting or
  CUDA_VISIBLE_DEVICES, no longer sees it. The operator names it in
  NEUROMESH_JOB_ENV_PASSTHROUGH. This changes behaviour for existing
  deployments.
- A sandbox that blocks the call stops the API, the agent and every job
  visibly at start, and does not fail silently.
- Every new place that starts a command must pass env. A test fails if a
  launch in the supervisor does not.

## Not Claimed

- That this is a complete sandbox for job commands. It closes one way for a
  command to reach the credentials of the process that runs it.
- That this works outside Linux. Nothing is done there.

## Alternatives Considered

- **Remove known names from the environment.** Rejected. A secret with
  another name would pass, and so would the next one added.
- **Run the command as another user.** Not rejected, only deferred. It needs
  a change to how the executor starts and its own ADR.
- **Rely on the container hardening of ADR 0058.** Rejected. A check inside a
  container with the compose flags showed that it does not close this.

## How to Verify

    pytest -q tests/application -k "job_environment or ancestors or process_hardening or passes_an_environment"
    pytest -q tests/scripts/test_run_agent_hardens_itself.py tests/presentation/test_lifespan_hardens_the_process.py

## Progress

2026-11-11. Every test was written first and failed for the expected reason
before the change. A check run inside a container with the compose flags
showed the problem without the change and its absence with it. That check
first ran against a control that was itself faulty, and the fault was
corrected in it and in the test before the result was accepted.

2026-11-11. The change and its tests are on main.
