import { expect, test } from "@playwright/test";
import { openChatWithToken } from "./support/chatSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

// P2PDialoguePanel renders live inter-agent telemetry (status/thought/
// tool_call events) pushed over the same chat websocket ChatPanel uses.
// It had zero e2e coverage before this file — unit tests stub
// useChatStore directly and never exercise the websocket -> store -> panel
// wiring end to end.
test.describe("P2P dialogue e2e (live telemetry over chat websocket)", () => {
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

  test("a reviewer telemetry event from a chat message appears on the P2P panel", async ({ page }) => {
    await page.getByLabel("Mesaj giriş alanı").fill("Merhaba backend");
    await page.getByRole("button", { name: "Gönder" }).click();
    await expect(page.getByText("Mock backend yanıtı")).toBeVisible();

    await page.getByRole("link", { name: "P2P Diyalog" }).click();

    await expect(page.getByRole("heading", { name: "Canlı P2P Ajan Diyaloğu" })).toBeVisible();
    const dialogue = page.getByRole("log", { name: "P2P diyalog olayları" });
    await expect(dialogue.getByText("reviewer:")).toBeVisible();
    await expect(dialogue).toContainText("Reviewer ajanı gelen mesajı inceliyor.");
  });
});
