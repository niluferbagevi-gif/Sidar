import { expect, test } from "@playwright/test";
import { openAdminRouteWithToken } from "./support/adminSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

// These panels write RBAC access policies and install/remove server-loaded
// plugin code — misconfiguration here has the highest blast radius of any
// UI surface in the app, but had zero e2e coverage before this file.
test.describe("Admin panels e2e (RBAC policy + plugin install)", () => {
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

  test("writes an RBAC access policy from the Tenant Admin panel", async ({ page }) => {
    await openAdminRouteWithToken(page, frontend.url, "Tenant Admin");

    await expect(page.getByRole("heading", { name: "Tenant Yönetim Paneli" })).toBeVisible();

    await page.getByLabel("Kullanıcı ID").fill("e2e-rbac-user");
    await page.getByLabel("Tenant ID").fill("e2e-tenant");
    await page.getByLabel("Kaynak tipi").selectOption("agents");
    await page.getByLabel("Aksiyon").selectOption("execute");
    await page.getByLabel("Kaynak ID").fill("coder");
    await page.getByLabel("Etki").selectOption("deny");

    await page.getByRole("button", { name: "Politikayı Kaydet" }).click();

    await expect(page.getByText("e2e-tenant tenant erişim politikası kaydedildi.")).toBeVisible();
    await expect(page.getByText("DENY · agents:coder")).toBeVisible();
    await expect(page.getByText("execute · user:e2e-rbac-user · tenant:e2e-tenant")).toBeVisible();
  });

  test("installs a plugin from the Plugin Marketplace panel", async ({ page }) => {
    await openAdminRouteWithToken(page, frontend.url, "Plugin Marketplace");

    await expect(page.getByRole("heading", { name: "Plugin Marketplace" })).toBeVisible();
    const pluginCard = page.locator(".marketplace-card", { hasText: "E2E Sample Plugin" });
    await expect(pluginCard).toBeVisible();
    await expect(pluginCard.getByText("Hazır", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Anında Yükle" }).click();

    await expect(
      page.getByText("Plugin işlemi tamamlandı: e2e-sample-plugin → Yükle."),
    ).toBeVisible();
    await expect(pluginCard.getByText("Canlı", { exact: true })).toBeVisible();
    await expect(page.getByText("1 aktif plugin")).toBeVisible();
  });
});
