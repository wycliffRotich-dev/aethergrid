# ADR 0080: Stop a Job's Processes When Their Owner Dies

## Status

Accepted. When the process that runs a job is killed outright, the
job's command and everything in its process group end with it. A test
that failed against the previous code shows it. The open questions of
the proposal are answered by Decisions 4 to 8, and the full suite
passes.

Related: ADR 0019, ADR 0029, ADR 0044, ADR 0079 and ADR 0081.

## Context

ADR 0079 makes execute() stop everything in the command's process
group before it returns. All of that cleanup is code in the process
that called execute(): a finally block and the SIGTERM and SIGKILL
escalation. A process that is killed outright runs none of it.
SIGKILL and the out-of-memory killer both end a process with no
chance to clean up. The command runs in its own session, so no signal
reaches it when its owner dies, and it keeps running.

For the standalone agent this breaks exclusive execution ownership.
The renewal thread dies with the agent, so the lease expires and the
job is reclaimed. It can then start on another worker while the first
run is still going. The two runs overlap until the orphan ends on its
own, and the first one is work done by a worker that no longer owns
the job.

Two hosts call JobExecutionService, and they are not in the same
position.

1. The API process builds one in app/presentation/dependencies.py.
   docker-compose.yml runs it as the neuromesh service. The service
   has no init entry, and the Dockerfile ends in exec uvicorn, so
   uvicorn is the first process of the container's PID namespace. The
   kernel kills every other process in a PID namespace when its first
   process dies. So a job started by the API process in the container
   should end with it. A probe under Evidence shows it.
2. The standalone agent, scripts/run_agent.py, is started by hand as
   python scripts/run_agent.py <node-id>. Nothing in the repository
   launches it. The Dockerfile copies app/ and not scripts/, and
   compose has no service for it. No container boundary or service
   manager is there to end its jobs, so the guarantee has to come
   from the code.

## Decision

1. The service starts the command through a supervisor, the module
   app.application.services.job_supervisor. execute() starts it with
   the interpreter of its own process, in a new session, so it leads
   a process group of its own. The -P option keeps the working
   directory off sys.path, so a job started in a directory with an
   app package of its own cannot make the supervisor import that one.
2. The supervisor starts the real command inside its own process
   group, so the two share the group, and waits for it. It starts the
   command itself, so there is no moment when the command is running
   and no process is watching its owner.
3. The supervisor holds the read end of a pipe, the watch pipe. Only
   the owner holds the write end. The owner's ends are not
   inheritable, so no other job started by the same process holds the
   write end. When the owner dies, however it dies, the kernel closes
   the write end, the supervisor reads end of file and sends SIGKILL
   to its own process group, which holds the command and what it
   started. A read that fails is treated the same way.
4. The result of the job is still the command's own result. The
   command inherits the supervisor's stdout and stderr, so nothing is
   relayed and the owner reads them as before. The supervisor ends
   the way the command did, with the same exit code, or by repeating
   the same signal on itself, so the owner reads the same negated
   signal number (ADR 0079, Decision 3).
5. The owner signals the same process group as before, with SIGTERM
   and then SIGKILL. The supervisor lives through SIGTERM with a
   function handler and not SIG_IGN, because an ignored signal stays
   ignored in a process that is started afterwards, and the command
   would stop obeying SIGTERM. The command decides what to do with it.
6. A command that cannot be started is reported on a second pipe, the
   status pipe, with the errno, the message and the file name. An
   exit code cannot carry it, because every value is also a code that
   a real command can return. The owner rebuilds the error. Only
   FileNotFoundError, PermissionError and NotADirectoryError become
   the failed result of ADR 0081. Any other error raises. A report
   that cannot be read is logged and ignored.
7. The owner waits for that report inside its polling loop, at most
   one poll interval at a time. A cancel, a lost lease or a timeout
   is acted on while the supervisor is still silent (ADR 0029 and
   ADR 0044).
8. A fault of the host while starting the supervisor, such as a
   missing interpreter, is not a fault of the job, so execute()
   raises, as ADR 0081 Decision 3 says.
9. The supervisor refuses to run unless it leads its own process
   group. It sends SIGKILL to that group, and it must not end
   processes that are not the job's.
10. The API process in its container is also covered by the container
    boundary. That holds only in a container. A uvicorn started by
    hand has no such guarantee, and the agent has none from the
    platform.

## Evidence

- test_job_execution_owner_death.py runs execute() in a script on a
  command that starts a child, kills the script with SIGKILL and
  asserts that the child is gone. It failed against main because the
  child outlived its owner, and it passes now.
- test_job_supervisor.py has eight tests on the supervisor alone: the
  exit code, a death by each of three signals, SIGTERM left to the
  command, the group killed on end of file, a launch failure on the
  status pipe, and the refusal without a group of its own. With the
  group kill replaced by a no-op, the end of file test failed.
- test_job_execution_result_contract.py has nine tests written
  against the code before the supervisor. They pin the exit code, a
  death by a signal, a timeout, a cancel, a lost lease, SIGTERM that
  the command handles or ignores, and the output, and they pass before
  and after. Making a stopped job report no exit code failed five.
- The seven tests of ADR 0081 pass through the supervisor unchanged.
- test_job_execution_supervisor_wiring.py has three tests written
  first. They failed against the first wiring: a missing interpreter
  was reported as a failed job, and a silent supervisor held a cancel
  and a lost lease until the launch wait ended. They pass now.
- test_job_execution_launch_report.py reads five unreadable reports
  and one complete report. test_job_execution_import_isolation.py
  starts a job in a directory that holds a decoy app package.
- test_job_supervisor_killed_alone.py kills only the supervisor and
  pins what follows (Not Claimed).
- Two probes ran in the app image. In the first, the container's
  first process ran a job and was killed with SIGKILL, and nothing of
  the job was left. That shows Decision 10 and not the supervisor,
  because the kernel ends the whole namespace. In the second, the
  first process was sleep 600, which stays alive. Two owners were
  started with docker exec and both were killed with SIGKILL. The job
  of the supervised owner and its supervisor were gone, the container
  still ran, and a job started the old way, with Popen and a new
  session, was still running. One run, on one machine, with sleep as
  the job.
- The full suite passes (1048). ruff and strict mypy are clean. The
  runs were on Python 3.12, and CI also runs 3.11.

## Consequences

- An agent killed outright no longer leaves a job running, and the
  overlap with a reclaimed job is cut to the time the kill takes.
- Every job starts one more process, and the supervisor is new code
  on the path of every job, with failure modes of its own.
- A supervisor killed on its own leaves the command running until the
  job ends.
- The agent depends on Linux behavior.

## Not Claimed

- A descendant that starts its own session or process group is not in
  the supervisor's group, so it is not killed. This is the limit of
  ADR 0079, and only a cgroup or a PID namespace contains it.
- That the kill happens before the lease expires. The supervisor sees
  end of file as soon as the kernel closes the pipe, but the time was
  not measured.
- A supervisor that is killed on its own. The command keeps running,
  the owner waits on the pipes the command holds, and the job ends at
  its timeout, when the owner signals the group. The result is a
  timeout with the exit code of the signal that ended the supervisor,
  and a test pins it. With a long timeout the command runs that long.
- A host process that is stopped and not killed, with SIGSTOP or a
  frozen machine. It keeps the pipe open, its lease expires and its
  command keeps running.
- The cost of starting a job. Importing the package took 0.041
  seconds against 0.039 for bare Python in one run, and the start of
  a job with the supervisor was not measured.
- Systems other than Linux were not tried.

## Alternatives Considered

- **PR_SET_PDEATHSIG on the command alone.** The kernel signals the
  command when its parent dies. It reaches the command and not what
  the command started, so the group is still orphaned. It is tied to
  the thread that started the command, and setting it needs a
  preexec_fn, which Python documents as unsafe with threads. The agent
  runs a renewal thread. Rejected as the mechanism. It may still be
  added to the command (Follow-ups).
- **A watchdog outside the command's group.** A helper holds the pipe
  and kills the group on end of file. It has to learn the group id
  after the command has started, so a host that dies in between leaves
  a command that nothing watches. The supervisor starts the command
  itself and has no such gap.
- **A cgroup per job.** cgroup.kill ends every process in a cgroup,
  including one that called setsid. It needs a delegated cgroup. The
  agent is started by hand and compose drops all capabilities from the
  app container, so it is not assumed (ADR 0079).
- **Leave it to the platform.** A container's first process, or a
  systemd unit with KillMode=control-group, ends the tree. That is
  right where a launcher exists, and Decision 10 uses it for the API
  process. The agent has no launcher in this repository. It is
  deployment advice and not the fix.
- **Sweep leftovers when the agent starts again.** It helps only if
  the agent comes back, and the leftover runs until then. Rejected
  as the fix.
- **Report a launch failure as a reserved exit code.** Every value is
  also a code that a real command can return, so the owner could not
  tell a failed launch from a command that chose that code. Rejected
  for the status pipe.

## Follow-ups

- Decide whether the command should ask the kernel to signal it when
  the supervisor dies, with PR_SET_PDEATHSIG. It would end the command
  and not what it started, and it is Linux only.
- Decide whether init: true belongs in compose, so that a leftover
  that is reparented to uvicorn is reaped.
- Measure the time between the death of the owner and the end of the
  group.
