import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TenantAdminPanel } from "./TenantAdminPanel.jsx";
import { fetchJson } from "../lib/api.js";

vi.mock("../lib/api.js", () => ({
  fetchJson: vi.fn(),
}));

const policiesPayload = {
  items: [
    {
      id: 1,
      user_id: "user-1",
      tenant_id: "acme",
      resource_type: "rag",
      resource_id: "*",
      action: "read",
      effect: "allow",
    },
  ],
};

const auditPayload = {
  items: [
    {
      id: 10,
      user_id: "user-1",
      tenant_id: "acme",
      action: "read",
      resource: "rag:*",
      allowed: true,
      timestamp: "2026-07-03T10:00:00Z",
    },
    {
      id: 11,
      user_id: "user-2",
      tenant_id: "acme",
      action: "manage",
      resource: "admin:*",
      allowed: false,
      timestamp: "2026-07-03T10:05:00Z",
    },
  ],
};

function mockFetchJson(url, options = {}) {
  if (url.startsWith("/admin/audit-logs")) return Promise.resolve(auditPayload);
  if (url.startsWith("/admin/policies/user-1") && !options.method) return Promise.resolve(policiesPayload);
  if (url === "/admin/policies" && options.method === "POST") return Promise.resolve(policiesPayload);
  return Promise.resolve({ items: [] });
}

describe("TenantAdminPanel", () => {
  beforeEach(() => {
    fetchJson.mockImplementation(mockFetchJson);
  });

  it("loads tenant audit logs from backend on initial render", async () => {
    render(<TenantAdminPanel />);

    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
    expect(await screen.findByText("rag:*")).toBeInTheDocument();
    expect(screen.getByText("admin:*")).toBeInTheDocument();
    expect(screen.getByText("İzinli audit").previousSibling).toHaveTextContent("1");
    expect(screen.getByText("Reddedilen audit").previousSibling).toHaveTextContent("1");
    expect(fetchJson).toHaveBeenCalledWith("/admin/audit-logs?tenant_id=default&limit=50");
  });

  it("lists policies for the selected user and tenant", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/policies/user-1?tenant_id=acme");
    });
    const policyCard = await screen.findByText("ALLOW · rag:*");
    expect(policyCard).toBeInTheDocument();
    expect(within(policyCard.closest(".policy-item")).getByText(/tenant:acme/)).toBeInTheDocument();
  });

  it("upserts a real RBAC policy through the admin policy API", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");
    await user.click(screen.getByRole("button", { name: "Politikayı Kaydet" }));

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/policies", expect.objectContaining({ method: "POST" }));
    });
    const [, request] = fetchJson.mock.calls.find(([url]) => url === "/admin/policies");
    expect(JSON.parse(request.body)).toMatchObject({ user_id: "user-1", tenant_id: "acme", resource_type: "rag" });
    expect(await screen.findByText("acme tenant erişim politikası kaydedildi.")).toBeInTheDocument();
  });
});
