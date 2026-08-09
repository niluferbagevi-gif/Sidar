import { expect, test } from "@playwright/test";
import { openAdminRouteWithToken } from "./support/adminSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

// PromptAdminPanel writes the system prompt every agent role loads on its
// next turn — a bad save here silently changes agent behavior fleet-wide,
// but had zero e2e coverage before this file.
test.describe("Prompt admin e2e (registry create + activate)", () => {
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

  test("creates a prompt, then activates a second version from the list", async ({ page }) => {
    await openAdminRouteWithToken(page, frontend.url, "Prompt Admin");

    await expect(page.getByRole("heading", { name: "Prompt Registry Admin" })).toBeVisible();
    await expect(page.getByText("Kayıt bulunamadı.")).toBeVisible();

    // The list filter ("role_name filtresi") is independent from the
    // create-form's own "Rol adı" field, so point it at the role under test
    // up front or newly created entries won't show up after each reload.
    await page.getByLabel("role_name filtresi").fill("e2e_reviewer");
    await expect(page.getByText("Kayıt bulunamadı.")).toBeVisible();

    await page.getByLabel("Rol adı").fill("e2e_reviewer");
    await page.getByLabel("Prompt metni").fill("E2E reviewer için sistem promptu v1.");
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();

    await expect(page.getByText("Prompt kaydedildi.")).toBeVisible();
    const firstEntry = page.locator(".data-list__item", { hasText: "e2e_reviewer" }).first();
    await expect(firstEntry.locator(".pill")).toHaveText("v1");
    await expect(firstEntry.getByRole("button", { name: "Aktif" })).toBeDisabled();

    await page.getByLabel("Prompt metni").fill("E2E reviewer için sistem promptu v2.");
    await page.getByLabel("Kaydeder kaydetmez aktif yap").uncheck();
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();

    await expect(page.getByText("Prompt kaydedildi.")).toBeVisible();
    const entries = page.locator(".data-list__item", { hasText: "e2e_reviewer" });
    await expect(entries).toHaveCount(2);

    const v2Entry = entries.filter({ hasText: "v2" });
    await v2Entry.getByRole("button", { name: "Aktif Yap" }).click();

    await expect(page.getByText("Aktif prompt sürümü v2 olarak güncellendi.")).toBeVisible();
    await expect(v2Entry.getByRole("button", { name: "Aktif" })).toBeDisabled();
  });
});
