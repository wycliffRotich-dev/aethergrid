import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useWorkerHeartbeatKeeper } from "./useWorkerHeartbeatKeeper";

const heartbeatWorkerMock = vi.fn();
const heartbeatNodeMock = vi.fn();

vi.mock("../api/workers", () => ({
  listWorkers: vi.fn(),
  heartbeatWorker: (...args: unknown[]) => heartbeatWorkerMock(...args),
}));

vi.mock("../api/nodes", () => ({
  heartbeatNode: (...args: unknown[]) => heartbeatNodeMock(...args),
}));

vi.mock("../api/dashboard", () => ({
  fetchNodes: vi.fn(),
}));

import { listWorkers } from "../api/workers";
import { fetchNodes } from "../api/dashboard";

describe("useWorkerHeartbeatKeeper", () => {
  beforeEach(() => {
    heartbeatWorkerMock.mockReset();
    heartbeatNodeMock.mockReset();
    heartbeatWorkerMock.mockResolvedValue(undefined);
    heartbeatNodeMock.mockResolvedValue(undefined);
  });

  it("heartbeats an OFFLINE worker, not just live ones (regression test for the incident ADR 0041/0042 fixed)", async () => {
    /**
     * Reproduces the exact live incident: a worker with status
     * OFFLINE and no running job must still receive a heartbeat,
     * since that heartbeat is what Worker.heartbeat() (ADR 0041)
     * uses server-side to recover it back to IDLE. Before ADR 0042,
     * this hook filtered OFFLINE workers out before ever calling
     * heartbeatWorker on them, so that worker could never recover
     * for the rest of the session.
     */
    vi.mocked(listWorkers).mockResolvedValue({
      workers: [
        {
          id: "offline-worker-1",
          status: "OFFLINE",
          node_id: "node-1",
          running_job_id: null,
          last_seen_at: new Date().toISOString(),
        },
        {
          id: "idle-worker-1",
          status: "IDLE",
          node_id: "node-1",
          running_job_id: null,
          last_seen_at: new Date().toISOString(),
        },
      ],
    });

    vi.mocked(fetchNodes).mockResolvedValue({
      nodes: [
        {
          id: "node-1",
          cpu_cores: 8,
          memory_mib: 16384,
          vram_mib: 0,
          available_cpu_cores: 8,
          available_memory_mib: 16384,
          available_vram_mib: 0,
          is_alive: true,
          is_draining: false,
        },
      ],
    });

    renderHook(() => useWorkerHeartbeatKeeper());

    await waitFor(() => {
      expect(heartbeatWorkerMock).toHaveBeenCalledWith("offline-worker-1");
    });

    expect(heartbeatWorkerMock).toHaveBeenCalledWith("idle-worker-1");
    expect(heartbeatWorkerMock).toHaveBeenCalledTimes(2);
  });

  it("does not heartbeat a node that is not alive", async () => {
    vi.mocked(listWorkers).mockResolvedValue({ workers: [] });

    vi.mocked(fetchNodes).mockResolvedValue({
      nodes: [
        {
          id: "dead-node",
          cpu_cores: 8,
          memory_mib: 16384,
          vram_mib: 0,
          available_cpu_cores: 8,
          available_memory_mib: 16384,
          available_vram_mib: 0,
          is_alive: false,
          is_draining: false,
        },
      ],
    });

    renderHook(() => useWorkerHeartbeatKeeper());

    await waitFor(() => {
      expect(vi.mocked(fetchNodes)).toHaveBeenCalled();
    });

    expect(heartbeatNodeMock).not.toHaveBeenCalled();
  });
});
