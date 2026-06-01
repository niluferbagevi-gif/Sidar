import { defineConfig } from "@playwright/test";

const playwrightHostPlatformOverride =
  process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE || "auto-detect";
const e2eFrontendPort = Number(process.env.SIDAR_E2E_FRONTEND_PORT || "15173");
const e2eBackendPort = Number(process.env.SIDAR_E2E_BACKEND_PORT || "17860");
const e2eBaseURL = `http://127.0.0.1:${e2eFrontendPort}`;
const e2eBackendURL = `http://127.0.0.1:${e2eBackendPort}`;

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
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: e2eBaseURL,
    storageState: undefined,
    trace: "on-first-retry",
  },
  webServer: {
    command: `npm run dev -- --strictPort --port ${e2eFrontendPort}`,
    env: { SIDAR_BACKEND_URL: e2eBackendURL },
    url: e2eBaseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
