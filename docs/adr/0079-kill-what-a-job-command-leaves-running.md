# ADR 0079: Kill What a Job Command Leaves Running

## Status

Proposed. It becomes Accepted when a command that exits with a child
still running, and a command that dies on SIGTERM while a descendant
ignores it, both leave nothing running, shown by two tests that fail
on main today, and the full suite passes.

Related: ADR 0029 and ADR 0044.

## Context

JobExecutionService runs a job's command as a subprocess. ADR 0044
recorded that a job whose lease was lost kept running, and the service
now stops the command when the lease is lost, when the job is
cancelled and when it times out. Since #424 the command runs in its
own session and every signal goes to its process group, so the
command's children are stopped with it.

Two cases are still open, and both come from where the service stops
waiting.

1. The service waits with communicate(), which returns when the
   command's output pipes close and reaps the command. A command that
   starts a child with its output detached and then exits closes its
   pipes at once. execute() returns, the command is gone, and nothing
   signals the group afterwards, so the child keeps running.
2. To stop a command that is still running, the service sends SIGTERM
   to the group and waits for the grace period. It sends SIGKILL only
   if that wait times out. When the command dies on SIGTERM and a
   descendant ignores it but has detached its output, the wait ends
   at once, the SIGKILL is never sent and the descendant survives.

Both leave a process running after the job has ended. The system then
releases the node's resources and may give them to another job, while
the leftover still uses the node's CPU, memory and VRAM. The scheduler
counts them as free. That is resource accounting that is no longer
true, and for a lost lease it is work done by a worker that no longer
owns the job.

Both cases apply to every caller: the standalone agent
(scripts/run_agent.py) and the API process, which builds one service in
app/presentation/dependencies.py for the in-process execution loop.

## Decision

1. When execute() has finished waiting for the command, for any
   reason, it sends SIGKILL to the command's process group once more,
   before it returns. The reasons are a normal exit, a timeout, a
   cancel, a lost lease and any exception. A group with no member left
   is not an error.
2. SIGTERM stays the first signal for a command that is still running,
   with the grace period before SIGKILL. Whatever is still in the group
   once the command has ended gets SIGKILL straight away. Nothing is
   waiting for its output, the command that could have shut it down
   cleanly has gone, and a grace period would delay the end of every
   job that leaves a helper behind.
3. The result of the job is still the command's own result. Killing
   leftovers changes no field of it. A job whose command exits 0 and
   leaves a child behind succeeds, and the child is killed.
4. A command that means to keep something running after it exits no
   longer can. This is a behaviour change and is stated as one. Work
   that must outlive a job needs a mechanism of its own.

## Consequences

- A finished job leaves nothing in its process group, so the resources
  the scheduler frees are free.
- Lease loss now ends the whole tree even when the command exits on
  SIGTERM first, which closes the second case above.
- A leftover killed with SIGKILL gets no chance to clean up.
- Every normal end of a job costs one more signal call. When the
  group is empty it fails with no such process and is ignored.

## Not Claimed

- That every descendant is stopped. One that starts its own session or
  process group, with setsid, setpgid or a double fork, is outside the
  group and is not signalled. Only a cgroup or a PID namespace contains
  it, and this change does neither.
- That an agent or API process that is killed outright cleans up. No
  code runs in that case, the lease expires and the children keep
  running until they exit. That is a separate decision.
- That the group id cannot belong to another process by the time the
  last signal is sent. communicate() reaps the command first, so there
  is a short window in which its pid is free. Linux hands out pids in a
  rising cycle: five processes started in a row on the development
  machine got consecutive pids, and pid_max there is 4194304, so a pid
  is not reissued until the counter wraps. This was not tested under
  heavy process churn or on a host with a small pid_max.

## Alternatives Considered

- **Wait without reaping, then signal.** Wait for the command with
  waitid and WNOWAIT, signal the group while the command is still a
  zombie holding its pid, then reap it. This closes the window above
  completely. Rejected for now. communicate() reaps the command itself,
  so this means replacing it with reader threads for both pipes and a
  waitid or pidfd poll, which changes every execution path the existing
  tests cover. The gain is closing a window that needs a pid wrap.
  Revisit it if a deployment runs with a small pid_max.
- **SIGTERM and a grace period for leftovers of a finished command.**
  Rejected. It adds up to the grace period to the end of any job that
  leaves a helper behind, and the command that owned the helper has
  already gone.
- **Leave leftovers alone after a normal exit.** Rejected. It keeps
  the case where a finished job's node is released while its process
  still runs there.
- **Put each job in a cgroup or a PID namespace.** It would contain a
  descendant that calls setsid. Not attempted. docker-compose.yml drops
  all capabilities from the app container, and the agent needs its own
  decision.

## Follow-ups

- An agent or API process that is killed outright.
- A warning when leftovers had to be killed. After the command is
  reaped, a signal that finds a member means one was left, which the
  service could report.
