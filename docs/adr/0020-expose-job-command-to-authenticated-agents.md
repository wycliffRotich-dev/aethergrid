# ADR 0020: Expose Job.command to Authenticated Agents Only

## Status

Proposed

## Context

ADR 0012 built real subprocess execution with enforced timeouts,
`Job.command` and `Job.exit_code`, fully tested at the service
layer, but deliberately did not expose `Job.command` through the
public `CreateJobRequest` API. That absence is enforced by a test,
not left as a comment. ADR 0012 named the open question directly:
whether an authenticated caller should be trusted with arbitrary
command execution is a separate decision about scope and blast
radius, and it hadn't been made yet.

ADR 0019 introduces a standalone worker agent process that polls
the API for assigned work and executes it as a real subprocess,
on the agent's own machine. For that to function at all, the
agent has to learn what command to run. There is no way to build
a working poll endpoint without exposing `Job.command` to
something.

This ADR makes the decision ADR 0012 deferred, scoped narrowly
enough that it does not reopen the original concern.

## Decision

`Job.command` is exposed through a new endpoint,
`GET /workers/{worker_id}`, gated the same way every route in
this system is gated: a valid API key (ADR 0015). It is
deliberately not added to `GetJobResponse` or any endpoint a
public caller would use to inspect a job by its own ID.

This is a narrower exposure than a public read, not a
reclassification of the original decision:

- The caller must already hold a worker identity, not merely any
  valid API key used for browsing. In practice, only an agent
  process that itself registered as a worker (ADR 0019) has
  reason to call this endpoint.
- The response is scoped to the one job currently assigned to
  that specific worker, `worker.running_job`, never an arbitrary
  job by ID. A caller cannot use this endpoint to read the
  command of a job they were not assigned.
- `CreateJobRequest` remains exactly as ADR 0012 left it. A
  caller creating a job still cannot set an arbitrary command
  through the public surface. This ADR does not touch that
  boundary.

`Job.command` is still never accepted as caller input through any
public endpoint. Every job's command today is set only by
whatever internal process creates it (currently none do, per ADR
0012, jobs created through `CreateJobService` still have no
command). This ADR is about an agent reading a command that was
already set, not about widening who can set one.

## Consequences

### Positive

- Unblocks ADR 0019 without silently widening the original
  security boundary ADR 0012 drew. The decision is explicit,
  named, and scoped, not an implicit side effect of building the
  poll endpoint.
- The exposure surface is as small as it can be while still
  functioning: one worker, one job, the job already assigned to
  that exact worker.

### Negative

- This endpoint is reachable by any valid API key, not
  exclusively agent processes, since the system does not yet
  distinguish credential types by role (ADR 0015 defined one key
  tier for the whole system). That's a deliberate scope
  boundary, not an oversight: introducing a second key tier
  before a real agent exists in production would be exactly the
  premature complexity ADR 0018 already argues against. Worth
  revisiting once agents are actually running and the risk is
  measured rather than theoretical.
- `CreateJobService` still provides no way to actually set
  `Job.command`, so this endpoint has nothing real to return
  until that gap is separately closed. This ADR unblocks the
  agent's ability to read a command; it does not yet unblock
  anyone's ability to set one through the public API. That
  remains open, matching ADR 0012's original scope, deliberately
  not resolved here.

## Alternatives Considered

### Add Job.command to the existing public GetJobResponse

Rejected.

Would expose arbitrary job commands to any caller with a valid
API key browsing jobs by ID, exactly the broad exposure ADR 0012
declined to build. Reopens the original concern instead of
resolving it narrowly.

### Introduce a separate "agent" API key tier before exposing anything

Deferred.

A real improvement, distinguishing agent credentials from
dashboard credentials would tighten this further, but it's a
larger change to the authentication model (ADR 0015) than this
decision requires to unblock ADR 0019. Worth its own future ADR
if the single-tier model proves insufficient in practice.
