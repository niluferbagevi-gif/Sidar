import { expect, test } from "@playwright/test";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";

test.describe("ChatPanel websocket e2e", () => {
  let backend;

  test.beforeAll(async () => {
    backend = await startMockSidarBackend({ port: 7860 });
  });

  test.afterAll(async () => {
    await backend?.close();
  });

  test("token kaydedildikten sonra websocket bağlanır ve presence görünür", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("Token gerekli")).toBeVisible();

    await page.getByLabel("Bearer token").fill("e2e-test-token");
    await page.getByRole("button", { name: "Token Kaydet" }).click();

    await expect(page.getByText("Bağlı")).toBeVisible();
    await expect(page.getByText("👥 2 kişi")).toBeVisible();
  });

  test("mesaj gönderildiğinde backend stream yanıtı chat penceresinde görünür", async ({ page }) => {
    await page.goto("/");

    await page.getByLabel("Bearer token").fill("e2e-test-token");
    await page.getByRole("button", { name: "Token Kaydet" }).click();
    await expect(page.getByText("Bağlı")).toBeVisible();

    await page.getByLabel("Mesaj giriş alanı").fill("Merhaba backend");
    await page.getByRole("button", { name: "Gönder" }).click();

    await expect(page.getByText("Mock backend yanıtı")).toBeVisible();
  });
});
