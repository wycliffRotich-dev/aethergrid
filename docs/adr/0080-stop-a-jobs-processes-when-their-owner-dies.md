# ADR 0080: Stop a Job's Processes When Their Owner Dies

## Status

Proposed. Nothing is built. The decision below is the design to
review, and the Open Questions are what the first tests must answer.

Related: ADR 0019, ADR 0029, ADR 0044 and ADR 0079.

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
   should end with it. No test in this repository shows that yet.
2. The standalone agent, scripts/run_agent.py, is started by hand as
   python scripts/run_agent.py <node-id>. Nothing in the repository
   launches it. The Dockerfile copies app/ and not scripts/, and
   compose has no service for it. No container boundary or service
   manager is there to end its jobs, so the guarantee has to come
   from the code.

## Decision

1. The service starts the command through a supervisor, a small
   process that execute() starts in its own session, as it starts the
   command today. The supervisor starts the real command inside its
   own process group, so the two share the group.
2. The supervisor holds the read end of a pipe. Only the host process
   holds the write end, and the command does not inherit it. When the
   host process dies, however it dies, the kernel closes the write
   end. The supervisor reads end of file and sends SIGKILL to its own
   process group, which holds the command and what it started.
3. The supervisor, and not the host, starts the command, so there is
   no moment when the command is running and no process is watching
   its owner.
4. The result of the job is still the command's own result. The exit
   code, including a death by a signal, and the stdout and stderr the
   service returns are the same as without the supervisor
   (ADR 0079, Decision 3).
5. The host's own signalling does not change. It signals the same
   process group as before.
6. The API process in the container relies on the container boundary.
   A test shows that killing the first process of the container
   leaves nothing of a job running, and this ADR is amended with what
   it showed. It holds only in a container. A uvicorn started by hand
   has no such guarantee, and the agent has none from the platform.

## Open Questions

- How the supervisor gives back the command's exit status, and a
  death by a signal, and how stdout and stderr reach the host without
  the supervisor relaying them. Tests that compare the result with and
  without it have to answer this before it is built.
- A supervisor killed on its own leaves the command running. The
  command could ask the kernel to signal it when the supervisor dies,
  with PR_SET_PDEATHSIG. That covers the command and not what it
  started, and it is Linux only. Whether to add it is open.
- Whether the supervisor is a module run with the same interpreter or
  a separate script, and what it adds to the start of every job.
- Whether the agent supports only Linux. The tests for process groups
  read /proc, and the pipe and signal behavior here is what Linux
  does.
- Whether init: true belongs in compose, so that a leftover that is
  reparented to uvicorn is reaped.

## Planned Tests

Each test is written first and must fail on main for the stated
reason.

- A script runs execute() on a command that starts a child. The test
  waits for the child's pid, kills the script with SIGKILL and asserts
  that the child is gone. On main the child is still running.
- The result with the supervisor equals the result without it for a
  normal exit, a nonzero exit, a death by a signal, a timeout, a
  cancel and a lost lease, including stdout and stderr.
- A supervisor killed on its own, to show what the Open Questions say
  about it and not to hide it.
- Kill the first process of the API container while it runs a job and
  assert that nothing of the job is left.

## Not Claimed

- A descendant that starts its own session or process group is not in
  the supervisor's group, so it is not killed. This is the limit of
  ADR 0079, and only a cgroup or a PID namespace contains it.
- That the kill happens before the lease expires. The supervisor sees
  end of file as soon as the kernel closes the pipe, but the time was
  not measured.
- A host process that is stopped and not killed, with SIGSTOP or a
  frozen machine. It keeps the pipe open, its lease expires and its
  command keeps running.

## Alternatives Considered

- **PR_SET_PDEATHSIG on the command alone.** The kernel signals the
  command when its parent dies. It reaches the command and not what
  the command started, so the group is still orphaned. It is tied to
  the thread that started the command, and setting it needs a
  preexec_fn, which Python documents as unsafe with threads. The agent
  runs a renewal thread. Rejected as the mechanism. It may still be
  added to the command (Open Questions).
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
  right where a launcher exists, and Decision 6 uses it for the API
  process. The agent has no launcher in this repository. It is
  deployment advice and not the fix.
- **Sweep leftovers when the agent starts again.** It helps only if
  the agent comes back, and the leftover runs until then. Rejected
  as the fix.

## Consequences

- An agent killed outright no longer leaves a job running. The overlap
  with a reclaimed job is cut to the time the kill takes.
- Every job starts one more process, and the supervisor is new code on
  the path of every job, with failure modes of its own.
- The agent depends on Linux behavior.

## Follow-ups

- When this is accepted, ADR 0079 gets a dated entry saying that its
  follow-up about a process killed outright is done.
