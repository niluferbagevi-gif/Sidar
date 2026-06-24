import { expect, test } from "@playwright/test";
import { openChatWithToken } from "./support/chatSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

test.describe("Operations tools panel e2e", () => {
  test.describe.configure({ mode: "serial" });

  let backend;
  let frontend;

  test.beforeAll(async () => {
    backend = await startMockSidarBackend();
    frontend = await startTestViteServer({ backendUrl: backend.url });
  });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.addInitScript(() => localStorage.clear());
    await openChatWithToken(page, frontend.url);
  });

  test.afterAll(async () => {
    await frontend?.close();
    await backend?.close();
  });

  test("Poyraz ve Coverage araçları REST çıktısı üretir", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Poyraz & Coverage Kontrol Paneli" })).toBeVisible();

    await page.getByRole("button", { name: "Landing üret" }).click();
    await expect(page.getByText("Landing page tamamlandı.")).toBeVisible();
    await expect(page.getByText("Sidar landing page hazır")).toBeVisible();

    await page.getByRole("button", { name: "Analiz et" }).click();
    await expect(page.getByText("Coverage analiz tamamlandı.")).toBeVisible();
    await expect(page.getByText("core/router.py")).toBeVisible();
  });
});
