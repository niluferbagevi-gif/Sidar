import { expect } from "@playwright/test";

function base64UrlEncode(value) {
  return Buffer.from(JSON.stringify(value))
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Build a fake-but-decodable JWT for e2e purposes: App.jsx's client-side
 * admin routing (getTokenPrincipal/isAdminPrincipal in src/lib/api.js) reads
 * `role` out of the middle (payload) segment of any `.`-delimited 3-part
 * token — it never verifies the signature — so the mock backend only needs
 * a non-empty token and the frontend only needs this exact shape.
 */
export function buildFakeAdminToken(overrides = {}) {
  const header = base64UrlEncode({ alg: "none", typ: "JWT" });
  const payload = base64UrlEncode({
    sub: "e2e-admin",
    username: "e2e_admin",
    role: "admin",
    tenant_id: "default",
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...overrides,
  });
  return `${header}.${payload}.e2e-fake-signature`;
}

/**
 * Save an admin token, then reach an admin-gated panel via its nav link
 * (rather than page.goto-ing the route directly). The dev Vite proxy routes
 * any `/admin/*` path to the backend (it's also the REST prefix for
 * `/admin/policies`, `/admin/audit-logs`, etc.), so a full page navigation
 * to a client-side-only path like `/admin/tenants` gets misrouted in this
 * dev/e2e setup even though production's catch-all SPA handler resolves it
 * correctly. Clicking the in-app nav link is also closer to how a real
 * operator reaches these panels.
 */
export async function openAdminRouteWithToken(page, frontendUrl, navLabel, token = buildFakeAdminToken()) {
  page.on("pageerror", (error) => console.error("BROWSER ERR:", error));
  await page.goto(`${frontendUrl}/chat`);
  await page.waitForLoadState("networkidle");

  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "Token Kaydet" }).click();

  await page.getByRole("link", { name: navLabel }).click();
}
