import { expect } from "@playwright/test";

export async function openChatWithToken(page, frontendUrl, token = "e2e-test-token") {
  page.on("pageerror", (error) => console.error("BROWSER ERR:", error));
  await page.goto(`${frontendUrl}/chat`);
  await page.waitForLoadState("networkidle");

  await page.waitForSelector('[data-testid="ws-status"]', { timeout: 30_000 });
  const wsStatus = page.getByTestId("ws-status");
  await expect(wsStatus).toHaveAttribute("data-state", "unauthenticated");
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "Token Kaydet" }).click();
  await expect(wsStatus).toHaveAttribute("data-state", "connected");
}
