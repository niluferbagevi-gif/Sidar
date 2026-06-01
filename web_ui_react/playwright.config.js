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
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev -- --strictPort --port 5173",
    port: 5173,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
