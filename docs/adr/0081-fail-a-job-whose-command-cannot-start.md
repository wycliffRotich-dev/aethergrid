# ADR 0081: Fail a Job Whose Command Cannot Start

## Status

Accepted. A command that cannot be started is a failed job, and both
callers of JobExecutionService now report it as one. Seven tests
that failed against the previous code show it, and the full suite
passes.

Related: ADR 0012, ADR 0044, ADR 0079 and ADR 0080.

## Context

JobExecutionService starts a job's command with subprocess.Popen. When
the program does not exist, is not executable, or has a file where a
directory should be, Popen raises FileNotFoundError, PermissionError
or NotADirectoryError. execute() did not catch them, so the exception
left the service. A probe on main showed it: executing
/no/such/binary ended in FileNotFoundError. No test pinned that, and
neither caller handled it.

1. The standalone agent calls execute() from run_job, which has a
   finally block and no handler for these errors. The loop in main
   catches httpx errors, KeyboardInterrupt and AgentError, so nothing
   caught the exception there either. By that reading the agent
   process ends, and the job stays leased to a process that is gone.
2. The in-process loop calls execute() inside a try and finally with
   no except. The exception skipped everything after it. The worker
   was not marked failed, the lease was not released, the node's
   resources were not freed and no JobFailed event was recorded.

For the agent, the lease then expires and the job is reclaimed. The
next agent that takes it meets the same missing program. One cause is
a program that is not installed on that node. Another is a command
written wrong by a caller holding the jobs:execute scope (ADR 0054).

## Decision

1. execute() catches FileNotFoundError, PermissionError and
   NotADirectoryError from starting the command, and returns a result
   that is not succeeded. Its exit_code is None, and timed_out,
   cancelled and lease_lost are false. Popen is started on its own, so
   only the start is covered and not errors from inside the wait.
2. The stderr of that result gives the reason. The service logs a
   warning that names the program and the reason, and never the
   arguments, which can hold secrets.
3. Any other error from starting a command still raises. A failed fork
   or a bad argument is a fault of the host and not of the job, and
   failing the job for it could fail good jobs on a node that is
   briefly broken.
4. Neither caller changes. Both already send a result that is not
   succeeded down the failed path, and a failure report with no exit
   code is accepted by the request schema, the worker and Job.fail.
5. This is a change to execute(), stated as one. It no longer raises
   for these three errors.
6. The reason does not leave the agent. report_outcome sends the exit
   code and the lease id, so the reason is in the result and in the
   agent's log, and not on the server.

## Evidence

- Seven tests were written first and failed against main. Four are on
  the service: three commands that cannot start, a missing program, a
  program that is not executable and a path through a file, and one
  that checks the reason is named. One is on run_job with a mocked
  client, and it asserts the agent posts the failure to the fail route
  with a null exit code under the lease it held. Two are on the
  in-process loop, which assert the job is failed, the worker is idle,
  the lease is released, the node's resources are free and a JobFailed
  event is recorded. All seven pass now.
- The probe of a missing program on main raised FileNotFoundError out
  of execute(), and the same test runs raise it out of run_job and out
  of the loop.
- The full suite passes (1009). ruff and mypy are clean. The runs
  were on Python 3.12, and CI also runs 3.11.

## Consequences

- A job whose command cannot start is a failed job, recorded under its
  lease, so the agent keeps running and the node is released.
- A caller that relied on the exception no longer gets it. None was
  found in app or scripts.
- The cause of the failure is in the agent's log and not in the job
  record.

## Not Claimed

- That the agent process ended before this change. That was read from
  the code. The agent test shows that run_job raised and posted no
  report, and nothing ran main end to end.
- Whether a failed job is retried, how often, or onto which node. That
  was not read. A job retried onto a node without the program fails
  again there.
- That an operator can see why the job failed. The reason is not sent
  to the server.
- That every error from starting a command is covered. Only the three
  above are.

## Alternatives Considered

- **Catch the errors in each caller.** There are two callers and three
  call sites, each with its own cleanup. A new caller would repeat the
  hole. Rejected.
- **Report a conventional exit code such as 127.** The API takes a
  null code, and no process exited, so a number would invent an
  observation. Rejected.
- **Treat every OSError from starting a command as a failed job.**
  It would blame the job for faults of the host. Rejected.

## Follow-ups

- ADR 0080 starts the command through a supervisor, one process later.
  It has to give back this same failed result for a command that
  cannot start, and not an exit code of its own. A test for that goes
  with it.
  Done in ADR 0080, see Progress.
- A way for the reason to reach the server, so an operator can see it.

## Progress

2026-10-29. The follow-up about the supervisor is done in ADR 0080. A
command that cannot start is reported on a status pipe and becomes
this same failed result. The seven tests of this ADR pass through the
supervisor unchanged, and a missing interpreter, which is a fault of
the host, raises.
