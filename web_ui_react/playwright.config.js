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
  timeout: 75_000,
  expect: { timeout: 30_000 },
  fullyParallel: true,
  // Cold-start dalgalanmalarında yalnız başarısız testi yeniden çalıştır.
  // CI daha değişken runner yükleri için ek bir deneme hakkı kullanır.
  retries: process.env.CI ? 2 : 1,
  use: {
    storageState: undefined,
    trace: "on-first-retry",
  },
});