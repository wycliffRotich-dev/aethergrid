import { useEffect } from "react";

import { heartbeatWorker, listWorkers } from "../api/workers";
import { fetchNodes } from "../api/dashboard";
import { heartbeatNode } from "../api/nodes";

const HEARTBEAT_INTERVAL_MS = 20_000;

/**
 * Keeps every worker AND node alive for as long as the dashboard
 * is open, by heartbeating them on an interval well inside the
 * backend's 1-minute timeout.
 *
 * Workers and nodes have entirely separate liveness clocks
 * (Worker.heartbeat()/is_alive() and Node.heartbeat()/is_alive()
 * are independent), so both need to be kept alive independently
 * -- heartbeating one does not heartbeat the other.
 *
 * Deliberately heartbeats OFFLINE workers too, not just live
 * ones (ADR 0041): a worker can go OFFLINE while genuinely idle,
 * for example while a job it just finished is cancelled and its
 * lease released without touching last_seen_at, and heartbeating
 * it is exactly what brings it back to IDLE. Excluding OFFLINE
 * workers here would silently strand any worker that flips
 * OFFLINE while this tab is still open, since nothing else in
 * this hook would ever heartbeat it again -- defeating ADR 0041's
 * recovery path rather than using it. Nodes are unaffected by
 * this change; heartbeating an offline node is not part of this
 * fix and untouched (still gated on node.is_alive).
 *
 * This is a deliberate stand-in for a real worker/node agent
 * process, which doesn't exist in this project. It's honest
 * about what it does: things stay alive exactly as long as
 * someone has the dashboard open and polling on their behalf.
 * Close the tab, and both correctly go OFFLINE within a minute,
 * same as if a real agent process had crashed -- this doesn't
 * bypass MarkDeadWorkersService or node liveness detection.
 */
export function useWorkerHeartbeatKeeper(): void {
  useEffect(() => {
    async function heartbeatAll() {
      try {
        const [workersResponse, nodesResponse] = await Promise.all([
          listWorkers(),
          fetchNodes(),
        ]);

        const aliveNodes = nodesResponse.nodes.filter(
          (node) => node.is_alive,
        );

        await Promise.all([
          ...workersResponse.workers.map((worker) =>
            heartbeatWorker(worker.id),
          ),
          ...aliveNodes.map((node) => heartbeatNode(node.id)),
        ]);
      } catch {
        // Best-effort: a failed heartbeat cycle just means
        // affected workers/nodes age one interval closer to
        // their own timeout, which is the correct fallback,
        // not an error worth surfacing to the user.
      }
    }

    void heartbeatAll();

    const interval = setInterval(() => {
      void heartbeatAll();
    }, HEARTBEAT_INTERVAL_MS);

    return () => clearInterval(interval);
  }, []);
}
