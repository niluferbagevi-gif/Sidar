import { expect, test } from "@playwright/test";
import { openChatWithToken } from "./support/chatSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

test.describe("Swarm flow operation surface e2e", () => {
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

  test("node seçimi üzerinden hedefli rerun ve HITL isteği çalışır", async ({ page }) => {
    await page.getByRole("link", { name: "Swarm Akışı" }).click();

    await expect(page.getByRole("heading", { name: "Swarm Görev Akışı" })).toBeVisible();
    // "nightly_scan" appears twice (graph node + activity timeline); either is fine here.
    await expect(page.getByText("nightly_scan").first()).toBeVisible();

    // Two graph nodes have the title "Supervisor" (the root orchestration node and
    // the "agent-supervisor" role card) — target the root node by its node-type class
    // instead of an ambiguous accessible-name match.
    await page.locator(".swarm-graph__node--root").click();
    await page.getByRole("button", { name: "Bu Node’u Çalıştır" }).click();
    await expect(page.getByText("Seçili düğüm için hedefli swarm çalıştı: Supervisor")).toBeVisible();
    await expect(page.getByText("Mock swarm sonucu")).toBeVisible();

    await page.getByRole("button", { name: "İnceleme İsteği Aç" }).click();
    await expect(page.getByText(/HITL isteği oluşturuldu: hitl-e2e-/)).toBeVisible();
    await expect(page.getByText("Supervisor düğümü için operatör incelemesi")).toBeVisible();
  });
});
