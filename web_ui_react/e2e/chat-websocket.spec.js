import { expect, test } from "@playwright/test";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

test.describe("ChatPanel websocket e2e", () => {
  test.describe.configure({ mode: "serial" });

  let backend;
  let frontend;

  test.beforeAll(async () => {
    backend = await startMockSidarBackend();
    frontend = await startTestViteServer({ backendUrl: backend.url });
  });

  async function connectWithToken(page) {
    await page.goto(`${frontend.url}/chat`);
    await page.waitForLoadState("networkidle");

    const wsStatus = page.getByTestId("ws-status");
    await expect(wsStatus).toHaveAttribute("data-state", "unauthenticated");
    await page.getByLabel("Bearer token").fill("e2e-test-token");
    await page.getByRole("button", { name: "Token Kaydet" }).click();
    await expect(wsStatus).toHaveAttribute("data-state", "connected");
  }

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.addInitScript(() => localStorage.clear());
    await connectWithToken(page);
  });

  test.afterAll(async () => {
    await frontend?.close();
    await backend?.close();
  });

  test("token kaydedildikten sonra websocket bağlanır ve presence görünür", async ({ page }) => {
    await expect(page.getByTestId("ws-status")).toHaveAttribute("data-state", "connected");
    await expect(page.getByText("👥 2 kişi")).toBeVisible();
  });

  test("mesaj gönderildiğinde backend stream yanıtı chat penceresinde görünür", async ({ page }) => {
    await page.getByLabel("Mesaj giriş alanı").fill("Merhaba backend");
    await page.getByRole("button", { name: "Gönder" }).click();

    await expect(page.getByText("Mock backend yanıtı")).toBeVisible();
  });
});
