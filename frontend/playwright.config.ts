import { defineConfig } from "@playwright/test";

/**
 * Phase 1 (see the e2e-suite planning discussion): local-only for
 * now, no CI wiring yet. Assumes the real stack is already running
 * -- docker compose up -d (API + Postgres) and npm run dev
 * (frontend) -- the same way every manual verification tonight was
 * done, not a webServer-managed spin-up. CI integration (Phase 2)
 * will need its own orchestration and is deliberately out of scope
 * here.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
});
