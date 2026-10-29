# ADR 0083: End a Job When Its Supervisor Ends

## Status

Accepted. When the supervisor of a job has ended, execute() ends the
job's process group and returns, whether or not something still holds
the output pipes. Two tests that failed against the previous code show
it, and the full suite passes.

Related: ADR 0079 and ADR 0080.

## Context

execute() waits with communicate(), which returns when the output
pipes close. Anything in the job's process group that still holds
stdout or stderr keeps them open, so the wait does not end when the
supervisor does. Two cases follow.

1. A command exits and leaves a child that inherited its output. The
   supervisor ends with the command's own exit code, the pipes stay
   open and execute() waits for the timeout. The result is a timeout
   with exit code 0, so a command that succeeded is reported as timed
   out, and both callers treat that as a failed job.
2. The supervisor is killed on its own. The command holds the pipes,
   so the wait does not end and the job runs to its timeout. ADR 0080
   recorded this under Not Claimed, and a test pinned it.

ADR 0079 sends SIGKILL to the group when the wait ends. Its cases were
children whose output was detached, which close the pipes. A child
that holds the pipes was not covered, because the wait did not end and
the SIGKILL did not run.

A probe on the code before ADR 0080 printed timed_out True, exit_code
0 and succeeded False for a command that exits 0 and leaves a child
holding its pipes. So the first case did not come from the supervisor.

## Decision

1. When communicate() times out and the supervisor has ended, execute()
   sends SIGKILL to the group, collects the output and returns. The
   check runs on every pass of the polling loop, so the job ends
   within a poll interval of the supervisor ending.
2. The result is the supervisor's own. It is the command's exit code,
   or the negated number of the signal that ended the supervisor.
   timed_out, cancelled and lease_lost are false, because the job did
   not overrun and nobody stopped it.
3. A command that exits 0 and leaves a child behind succeeds, and the
   child is killed, as ADR 0079 Decision 3 says.
4. The output is collected with the termination grace period as its
   limit. If that limit passes, stdout and stderr are returned empty.
5. A supervisor that is still running is not affected. A command that
   hangs ends at its timeout, as before.

## Evidence

- test_job_execution_supervisor_ends.py has two tests, written first.
  Against main both failed because the job ran 10.0 seconds, to its
  timeout: one with the supervisor killed alone, and one with a
  command that exits and leaves a child holding its pipes. They pass
  now, and the file runs in under a second. With the check replaced by
  one that never fires, both failed again.
- A probe on 004086c, in a separate worktree of the commit before ADR
  0080, printed timed_out True, exit_code 0 and succeeded False.
- test_job_supervisor_killed_alone.py pinned the old behavior of the
  second case. The new file replaces it.
- The nine tests of the result contract, the tests of ADR 0081 and the
  process group tests of ADR 0079 pass unchanged.
- The full suite passes (1073). ruff and strict mypy are clean. The
  runs were on Python 3.12, and CI also runs 3.11.

## Consequences

- A job ends within a poll interval of its supervisor ending, and its
  group is killed.
- A command that succeeds and leaves a helper behind is reported as
  succeeded and not as timed out.
- A supervisor killed on its own ends the job with the exit code of
  the signal that ended it, and no timeout flag.
- ADR 0080 states the old behavior in Consequences and Not Claimed.
  Those entries are kept, and its Progress section points here.

## Not Claimed

- A descendant that starts its own session and holds the pipes. The
  group kill does not reach it, so the collection waits out the grace
  period, returns empty output and leaves the descendant running.
- The time between the supervisor ending and the return. The tests
  bound it at five seconds and nothing more precise was measured.
- A command that hangs while its supervisor is alive. It ends at its
  timeout.

## Alternatives Considered

- **Wait for the supervisor, then read the pipes.** The pipes stay open
  while a child holds them, so the read waits all the same.
- **Send output to files and not pipes.** A child cannot hold a file
  open against the owner, but it changes how output reaches the
  caller, and every execution path the existing tests cover. Not
  attempted.
- **Read the pipes on threads and join with a timeout.** It replaces
  communicate(), which ADR 0079 weighed and set aside. It is larger
  than the gap.

## Follow-ups

- Return the output read so far when the collection after the kill
  times out.
- Decide whether the PR_SET_PDEATHSIG follow-up of ADR 0080 is still
  needed.
