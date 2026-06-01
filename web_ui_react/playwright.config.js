import { defineConfig } from "@playwright/test";

const playwrightHostPlatformOverride =
  process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE || "auto-detect";
export default defineConfig({
  testDir: "./e2e",
  metadata: { playwrightHostPlatformOverride },
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  outputDir: "test-results",
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  retries: 0,
  use: {
    storageState: undefined,
    trace: "on-first-retry",
  },
});
