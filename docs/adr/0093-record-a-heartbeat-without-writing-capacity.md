# ADR 0093: Record a Heartbeat Without Writing Capacity

## Status

Accepted. The change, the race test and the contract tests are on branch
fix/reclaim-saves-job-before-releasing-node.

Related: ADR 0064 and ADR 0092.

## Context

HeartbeatNodeService read the node, called Node.heartbeat() and saved the
whole row. The row includes the node's available CPU, memory and VRAM.
If the scheduler allocated capacity on the node between the read and the
save, the heartbeat wrote the older available figures back over the
allocation. The node then offered capacity that was already promised.

test_heartbeat_does_not_erase_a_concurrent_allocation shows it on real
Postgres. A node with 8 cores free is read, 1 core is allocated by
another writer, and the heartbeat is saved. The stored node reports 8
cores free where it should report 7. The test forces that order
itself, so it shows the lost update on a real database without
running two writers at the same time.

## Decision

1. NodeRepository gains record_heartbeat(node_id, tenant_id, seen_at).
   It writes last_seen_at and nothing else, and returns True when a node
   with that id exists in that tenant.
2. A node in another tenant, or no node at all, returns False, and the
   stored row is not changed. This matches the way a foreign node reads
   everywhere else (ADR 0064).
3. HeartbeatNodeService calls record_heartbeat with the current time. It
   no longer reads, changes and saves the node. When the call returns
   True it reads the node back and returns it, so its callers see the
   same result as before.
4. All three backends implement the method, and a contract test checks it
   on each of them.

## Consequences

- A heartbeat carries no capacity figures, so it cannot write any back.
- The service makes two repository calls where it made two before, but
  the first one is now a single targeted write.
- Adding an abstract method means a new backend cannot start without
  implementing it.

## Not Claimed

- That capacity updates are safe in general. The scheduler, outcome
  reporting, the worker loop, node draining and reclaim_job still read a
  node, change it and save the whole row, so two of them acting on one
  node at the same time can still overwrite each other. This ADR fixes
  the heartbeat only.
- That the node returned by the service is the same snapshot that the
  heartbeat wrote. It is read back after the write, so another writer's
  change in between is visible in it, and a node deleted in between
  makes the service return None.
- That the in-memory backend can show the race. It shares one object
  between callers, so the race test runs on Postgres only.
- That the race was seen with two writers running at once. The test
  puts the allocation between the service's read and its write, and
  does not use threads.

## Alternatives Considered

- **Keep the read, change and save, and add a version check.** Rejected
  for the heartbeat. A heartbeat would fail and retry whenever the
  scheduler wrote, and it carries no data that needs the whole row.
- **Make every node write a delta.** Not rejected, only deferred. It
  is the real fix for the other writers named above and needs its own
  ADR.

## How to Verify

    pytest -q tests/infrastructure/repositories -k "record_heartbeat or heartbeat_keeps"

All of them pass. Before this change the Postgres race test fails with 8
equal to 7.

## Progress

2026-11-10. The race test was written first and failed with
assert 8 == 7 against Postgres before the fix. After the fix the full
suite passed with 1324 tests, with the backend set to postgres.

The four contract tests were added afterwards. To check that they guard
the write, record_heartbeat in the in-memory backend was changed to do
nothing, and exactly two of them failed, the one that checks only the
heartbeat time changes and the one that makes a stale node available
again. The file was restored and they passed. The two tests that check
the return value for a missing node and another tenant were not checked
this way. The node repository tests passed with 85 tests after the
contract tests were added. The full suite then passed with 1336 tests,
with the backend set to postgres.
