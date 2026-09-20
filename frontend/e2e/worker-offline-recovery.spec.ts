import { test, expect, request as playwrightRequest } from "@playwright/test";

/**
 * Phase 1 e2e test: reproduces the real live incident ADR 0041 and
 * ADR 0042 (#222-#226) fixed, end to end through the real stack, not
 * mocked. Requires docker compose (API + Postgres) and the frontend
 * dev server already running locally, and a real API key exported
 * as PLAYWRIGHT_API_KEY (see scripts/issue_api_key.py).
 *
 * Deliberately waits out the real 60s HEARTBEAT_TIMEOUT rather than
 * manipulating backend state directly (an external e2e process has
 * no way to reach into the Python repository the way
 * test_worker_heartbeat_api.py does). A worker is registered via the
 * real API without ever opening the dashboard, so nothing heartbeats
 * it, then polled via the real API until MarkDeadWorkersService
 * marks it OFFLINE on its own 1s reconciliation cadence. Only then
 * does the dashboard open, so useWorkerHeartbeatKeeper's own 20s
 * cycle is the thing under test, not a shortcut around it.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE ?? "http://localhost:8000";
const API_KEY = process.env.PLAYWRIGHT_API_KEY;

test.describe("worker OFFLINE recovery (ADR 0041 / ADR 0042)", () => {
  test.skip(
    !API_KEY,
    "PLAYWRIGHT_API_KEY must be set. Issue one with " +
      "python scripts/issue_api_key.py 'e2e-local' and export it.",
  );

  test("a worker that goes OFFLINE from a stale heartbeat recovers to IDLE once the dashboard's heartbeat keeper reaches it", async ({
    page,
  }) => {
    test.setTimeout(150_000);

    const api = await playwrightRequest.newContext({
      baseURL: API_BASE,
      extraHTTPHeaders: { Authorization: `Bearer ${API_KEY}` },
    });

    const nodeResponse = await api.post("/nodes", {
      data: { cpu_cores: 8, memory_mib: 16384, vram_mib: 8192 },
    });
    expect(nodeResponse.ok()).toBeTruthy();
    const { id: nodeId } = await nodeResponse.json();

    const workerResponse = await api.post("/workers", {
      data: { node_id: nodeId },
    });
    expect(workerResponse.ok()).toBeTruthy();
    const { id: workerId } = await workerResponse.json();

    const initial = await api.get(`/workers/${workerId}`);
    expect((await initial.json()).status).toBe("IDLE");

    await expect
      .poll(
        async () => {
          const response = await api.get(`/workers/${workerId}`);
          return (await response.json()).status;
        },
        {
          timeout: 90_000,
          intervals: [2_000],
          message: "worker never went OFFLINE via real HEARTBEAT_TIMEOUT",
        },
      )
      .toBe("OFFLINE");

    await page.addInitScript(
      ({ storageKey, key }) => {
        window.sessionStorage.setItem(storageKey, key);
      },
      { storageKey: "aethergrid_api_key", key: API_KEY as string },
    );

    await page.goto("/workers");

    const workerRow = page.getByRole("row", {
      name: new RegExp(workerId.slice(0, 8)),
    });

    await expect(workerRow).toContainText(/offline/i);

    await expect(workerRow).toContainText(/idle/i, {
      timeout: 30_000,
    });
  });
});
