import { useEffect } from "react";

import { heartbeatWorker, listWorkers } from "../api/workers";
import { fetchNodes } from "../api/dashboard";
import { heartbeatNode } from "../api/nodes";

const HEARTBEAT_INTERVAL_MS = 20_000;

/**
 * Keeps every non-offline worker AND node alive for as long as
 * the dashboard is open, by heartbeating them on an interval
 * well inside the backend's 1-minute timeout.
 *
 * Workers and nodes have entirely separate liveness clocks
 * (Worker.heartbeat()/is_alive() and Node.heartbeat()/is_alive()
 * are independent), so both need to be kept alive independently
 * -- heartbeating one does not heartbeat the other.
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

        const aliveWorkers = workersResponse.workers.filter(
          (worker) => worker.status !== "OFFLINE",
        );

        const aliveNodes = nodesResponse.nodes.filter(
          (node) => node.is_alive,
        );

        await Promise.all([
          ...aliveWorkers.map((worker) => heartbeatWorker(worker.id)),
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
