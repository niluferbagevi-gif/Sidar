import { expect, test } from "@playwright/test";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";

const e2eBackendPort = Number(process.env.SIDAR_E2E_BACKEND_PORT || "17860");

test.describe("ChatPanel websocket e2e", () => {
  let backend;

  test.beforeEach(async ({ page }) => {
    backend = await startMockSidarBackend({ port: e2eBackendPort });
    await page.context().clearCookies();
    await page.addInitScript(() => localStorage.clear());
  });

  test.afterEach(async () => {
    await backend?.close();
    backend = undefined;
  });

  test("token kaydedildikten sonra websocket bağlanır ve presence görünür", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("Token gerekli")).toBeVisible({ timeout: 15_000 });

    await page.getByLabel("Bearer token").fill("e2e-test-token");
    await page.getByRole("button", { name: "Token Kaydet" }).click();

    await expect(page.getByText("Bağlı")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("👥 2 kişi")).toBeVisible({ timeout: 15_000 });
  });

  test("mesaj gönderildiğinde backend stream yanıtı chat penceresinde görünür", async ({ page }) => {
    await page.goto("/");

    await page.getByLabel("Bearer token").fill("e2e-test-token");
    await page.getByRole("button", { name: "Token Kaydet" }).click();
    await expect(page.getByText("Bağlı")).toBeVisible({ timeout: 15_000 });

    await page.getByLabel("Mesaj giriş alanı").fill("Merhaba backend");
    await page.getByRole("button", { name: "Gönder" }).click();

    await expect(page.getByText("Mock backend yanıtı")).toBeVisible({ timeout: 15_000 });
  });
});
