import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    // e2e/ is Playwright's suite, a different runner with a
    // different test API (test.describe/test.skip mean something
    // else there). Vitest's default discovery would otherwise pick
    // up e2e/*.spec.ts alongside its own tests and fail trying to
    // interpret Playwright's API as its own.
    exclude: ["**/node_modules/**", "**/e2e/**"],
  },
});
