# ADR 0044: Agent Retries Transient Failures With Capped Backoff and Jitter

## Status

Accepted

## Context

`scripts/run_agent.py` (ADR 0019) is meant to run unattended, one
process per node. Its failure handling did not match that goal.

Only two call paths caught `httpx.HTTPError`: the background
heartbeat thread, which logged and continued, and lease renewal,
which treated any error as a lost lease. Every other call used a
bare `raise_for_status()`:

- Registration, and the two initial heartbeats, so a single 429,
  5xx, or timeout at startup killed the process.
- The poll in the main loop, so the same errors killed a running
  agent. A 404 there also killed it, although ADR 0030 records
  that removing a node cascades to its workers, which makes 404 a
  reachable state for a healthy agent.
- Job start, and the outcome report after a job had already run.

Lease renewal was worse than crashing. `renew_lease()` returns
"lost" only on 409, but any other error, including a transient
429 or 5xx, propagated to the caller, which set the lost-lease
flag. The agent then discarded the result of a job that had
finished successfully while its lease was still valid on the
server.

There was also no backoff or jitter anywhere. After a control
plane restart, every agent fails at the same moment, and a
supervisor that restarts them brings them back in lockstep, which
is the worst possible load shape for a recovering API.

## Decision

Failures are classified, and each class has one response.

Transient (429, any 5xx, and transport errors such as connect
failures and timeouts) are retried without limit, with capped
exponential backoff and full jitter, never sooner than the
server's `Retry-After`. The delay ceiling starts at 1 second,
doubles per attempt, and is capped at 30 seconds. Retries are
unbounded on purpose: an unattended agent must outlast a control
plane outage, and the operator stops it with Ctrl+C.

This applies to registration, the initial heartbeats, the poll,
and the outcome report. Retrying registration is safe because it
is idempotent per node (ADR 0030). Retrying the outcome report is
safe because it is fenced by lease identity (ADR 0036): if an
earlier attempt was applied and only its response was lost, the
retry receives 409 and is dropped, which is the correct result.

Stale view (404 or 409 where the agent's belief about what it
owns is no longer true) returns the agent to the poll loop, which
re-reads the server's state. A 404 on the poll means the worker
row is gone, so the agent re-registers, which is always safe.

Anything else (401, 422, and a 404 on registration) stops the
agent with a message that names the request and status. Retrying
cannot fix these, and looping would hide a misconfiguration.

Lease renewal keeps its existing contract: only 409 means the
lease is lost. A transient failure is retried with backoff until a
trust window closes. The window is the lease duration minus one
poll interval, measured from the last confirmed renewal on the
agent's own monotonic clock. The margin exists because the lease
can already be up to one poll interval old when the agent first
sees it, so trusting it for the full duration would outlast the
real expiry. Past the window, or on a non-transient error, the
lease is treated as lost, as before.

Steady-state heartbeat and poll intervals are spread by 20 percent
either side, so agents started together drift apart.

## Consequences

### Positive

- An agent survives a control plane restart, an overload, and
  rate limiting without operator action, and resumes on its own.
- A finished job's result is no longer discarded because of one
  transient error during renewal.
- A fleet that fails together no longer retries together.
- A worker deleted out from under a healthy agent is recovered by
  re-registering instead of a crash.
- The change is confined to `scripts/run_agent.py`. The
  `renew_lease()` contract pinned by its existing tests is
  unchanged, and the API is untouched.

### Negative

- An agent pointed at a wrong URL retries forever instead of
  exiting. The retry log makes this visible, but it is a real
  tradeoff of unbounded retry.
- Retries do not raise the rate limit. ADR 0021 gives one shared
  key a bucket of 60 tokens refilling at 10 per second, and an
  idle agent makes about 0.6 requests per second, so a shared key
  supports on the order of 14 concurrent agents before throttling
  begins. Backoff makes an agent behave well when throttled, but
  it cannot remove that ceiling. Fleet-scale credentials need a
  separate decision.
- This does not stop a job whose lease was lost. The lost-lease
  flag is only checked after the subprocess exits, so a reclaimed
  job can still run to completion on the agent. That gap is
  unchanged and is left to a separate decision.

  **Resolved (2026-09-25):** `JobExecutionService.execute()` now
  accepts a `lease_lost_event`, polled on the same cadence as
  `cancel_event`, and preempts the subprocess via the existing
  SIGTERM-then-SIGKILL escalation the moment a lease loss is
  detected, instead of only after the subprocess exits. See the
  `fix/agent-preempts-subprocess-on-lease-loss` PR.

## Alternatives Considered

### Bounded retries, then exit

Rejected. An outage longer than the bound would kill every agent,
which then depends on an external supervisor to restart them,
and the restarts arrive together. Unbounded retry with jitter
keeps the fleet alive and spread out.

### Retry inside each API function

Rejected. Registration, poll, and outcome reporting need
different classifications of the same status code (a 404 is fatal
on registration but means re-register on the poll, and a 409 is a
dropped result on the outcome report). One shared retry helper
plus caller-specific handling keeps those decisions visible at the
call sites.

### Add a retry library

Rejected. The policy is about thirty lines and has to be tested
deterministically, which is easy with injected sleep and random
number generator and would be harder through a library's clock.

## References

- ADR 0019: Standalone Worker Agent Process
- ADR 0021: Per-API-Key Rate Limiting
- ADR 0030: Idempotent Worker Registration Per Node
- ADR 0036: Fence Outcome Reports by Lease Identity for Agents
