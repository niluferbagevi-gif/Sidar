import { expect, test } from "@playwright/test";
import { openAdminRouteWithToken } from "./support/adminSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

// AgentManagerPanel uploads a Python file straight into the live swarm
// ecosystem via multipart POST — arguably the highest blast-radius upload
// surface in the app (it registers executable agent code), but had zero
// e2e coverage before this file. Unit tests can't exercise the real
// browser File/FormData path this component depends on.
test.describe("Agent manager e2e (plugin agent file upload)", () => {
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
  });

  test.afterAll(async () => {
    await frontend?.close();
    await backend?.close();
  });

  test("uploads a Python agent file and shows the registered agent metadata", async ({ page }) => {
    await openAdminRouteWithToken(page, frontend.url, "Agent Manager");

    await expect(page.getByRole("heading", { name: "Agent Manager" })).toBeVisible();
    await expect(page.getByText("Seçilmedi")).toBeVisible();

    await page.setInputFiles('input[type="file"]', {
      name: "e2e_custom_agent.py",
      mimeType: "text/x-python",
      buffer: Buffer.from("class E2ECustomAgent:\n    pass\n"),
    });
    await page.getByLabel("Role name").fill("e2e_custom_agent");
    await page.getByLabel("Class name").fill("E2ECustomAgent");
    await page.getByLabel("Capabilities").fill("automation, e2e_capability");
    await page.getByLabel("Sürüm").fill("2.0.0");

    await expect(page.getByText("e2e_custom_agent.py")).toBeVisible();

    await page.getByRole("button", { name: "Ajanı Kaydet" }).click();

    await expect(page.getByText("e2e_custom_agent ajanı yüklendi. Sürüm: 2.0.0")).toBeVisible();
    const preview = page.locator(".code-block");
    await expect(preview).toContainText('"role_name": "e2e_custom_agent"');
    await expect(preview).toContainText('"version": "2.0.0"');

    // Successful submit resets the form.
    await expect(page.getByText("Seçilmedi")).toBeVisible();
  });
});
